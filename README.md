# Dual RX 7900 XTX on Windows with Strata — fixes, configs and launchers

Running **two AMD RX 7900 XTX cards as one inference engine on Windows** with the
[Strata](https://github.com/Niko1221/Strata) RDNA3 fork
([nicejunjie/Strata-rdna3](https://github.com/nicejunjie/Strata-rdna3), base commit `bd34f079`).

中文说明见文末。

## The core bug

On Windows, the fork's tensor-parallel path uploads GGUF weight column slices with
`hipMemcpy2D`. When the source is a **read-only Windows file mapping**
(`MapViewOfFile`, `FILE_MAP_READ`) — which is how the GGUF weights are mapped — the
call **returns success but silently uploads wrong data** (in our test slice,
8,323,025 of 8,355,840 bytes differ, on both cards, on Gen3 and Gen4 links alike).
The model loads "fine" and then produces garbage. A standalone ctypes repro that
bypasses the engine's C++ entirely is in [`repro/hip_copy_diagnostic.py`](repro/hip_copy_diagnostic.py);
measured results in [`repro/hip-copy-gen4-diagnostic.json`](repro/hip-copy-gen4-diagnostic.json).

**Fix:** at load time, gather each column slice into one contiguous CPU buffer and
upload it with a single 1-D `hipMemcpy` (`STRATA_TP_UPLOAD_PACKED=1`). After the fix,
all 240 checked slices (144 row + 96 column) read back byte-identical.

## What is in this repo

| Path | Contents |
|---|---|
| `patches/base-tree-vs-bd34f079.patch` | Working-tree delta of the build tree vs the fork base commit: `STRATA_NO_HSA=1` on Windows, a `pid_t` portability fix, an opt-in SDMA PCI allowlist (`STRATA_HSA_COPY_PCI`), an opt-in megakernel dynamic-scheduling flag |
| `patches/fix-windows-tp-upload.patch` | The packed-upload fix for TP column slices (the core fix above) |
| `patches/service-during-launch.patch` | `STRATA_TP_SERVICE_DURING_LAUNCH=1`: the main thread services CPU expert requests while TP launch submission is in flight, instead of misreading "not yet queued" as "done" |
| `patches/main-keep-cache.patch` | DP options `STRATA_DP_MAIN_ONLY` / `STRATA_DP_MAIN_KEEP_CACHE` / `STRATA_DP_FINAL_PUBLISH`: main card runs long-input prefill while the idle card keeps its expert cache |
| `patches/shared-kv.patch` | DP foreign sessions borrow the owner session's pinned host KV instead of allocating a duplicate — skips 12 runtime allocations of 1,107,297,280 bytes each, **12.375 GiB** of pinned memory in total |
| `patches/check-all-uploads.patch` | Diagnostic variant that byte-checks every upload (row + column slices); not for production runs |
| `build/` | `make_*.py` generators that produce the candidate sources from the tree originals, and `build_*.py` scripts that compile only the changed objects with the original Ninja flags and link them ahead of the stock library |
| `repro/hip_copy_diagnostic.py` | Standalone ctypes repro of the `hipMemcpy2D` / read-only-mapping corruption |
| `launchers/` | The final dual-card MTP + Vision launcher BATs (256K and 1M context), the launcher generator `make_dual_vision_launchers.py`, a launch checker, and the two exact service configs they run |
| `docs/` | Full engineering reports (Chinese): mechanism isolation for the TP upload bug, the Gen4 dual-card validation and tuning log, the M.2 Gen4 single-card follow-up, and a consolidated troubleshooting guide |

## Test rig

- i9-13900KF, 128 GB DDR4, ASUS PRIME Z690-P D4, Windows 11
- GPU 1 (main slot): RX 7900 XTX, PCIe Gen4 x16 — pinned H2D ≈ 26.7 GB/s
- GPU 0 (external dock, M.2_2 → OCuLink): RX 7900 XTX, PCIe Gen4 x4 — pinned H2D ≈ 7.0 GB/s
- Model: Qwen3.8-Flash-Next UD-IQ4_XS, MTP drafting (spec 4, min-p 0.70), full routing
- Benchmark protocol unless stated otherwise: exact 65,536-token input / 256 output,
  no prompt or conversation cache, temperature 0, seed 42, thinking off,
  correctness = all embedded passphrases retrieved + exact input/output counts

## Verified results (medians of 3 runs, protocol above)

| Configuration | Prefill tok/s | Decode tok/s |
|---|---:|---:|
| Dual card, original DP prefill + TP decode, 2 stager threads/GPU | **3589.2** | **100.0** |
| Dual card, main-card long-input prefill + TP decode | 2990.2 | 96.0 |
| Same engine, main-slot single card (matched settings) | 3281.2 | 53.9 |
| Same engine, dock single card on the old Gen3 link | 1437.8 | 31.0 |

Dual-card prefill on this branch is a capacity feature, not a speedup over the
main-slot card alone; the dual-card win is decode throughput and context capacity.

Final delivered configs (`launchers/`):

- **256K**: `engine-service` build, expert arena pin 32 GiB, VRAM reserve 2560 MiB.
  Vision on; a 261,888-token input retrieved all passphrases.
- **1M**: `engine-shared-kv` build, pin 16 GiB, VRAM reserve 2048 MiB, expert lend 97,
  auto chunk back to 32,768. Cold 64K ≈ 3146–3192 prefill, 128K input verified
  (3449.6 prefill / 85.2 decode on the live config). A separate long real-world
  session cold-read 728,780 tokens in one pass and grew to ~762K tokens of context
  with ~99.9% cache reuse per follow-up turn.

## Known limitations — read before citing

- **One intermittent cold-start wrong answer is on record and its root cause is
  NOT located.** The same stage-2 config later passed 3 + 3 repeated cold starts.
  The launchers are therefore labelled **Test**; this is not claimed to be a
  fully stable production build.
- **A full 1,048,576-token single input has never been run.** "1M" is the configured
  context cap; the longest verified single input is 261,888 tokens (256K config)
  and 131,072 tokens (1M config), plus the ~729K cold read in a real session.
- DFlash2 drafting is single-card-only in this fork build; the dual-card configs
  use MTP.
- Card numbering (`gpu=[1,0]`) follows this machine's PCI topology
  (main slot = 0000:03:00.0, dock = 0000:07:00.0). Re-check on any other machine;
  the fork's HIP index order is not the physical slot order.

## Build / apply sketch

1. Clone the fork at `bd34f079`; apply `patches/base-tree-vs-bd34f079.patch`; build
   with the fork's `tools\hip\build_windows.bat`.
2. Generate and build the candidate objects with the scripts in `build/`
   (packed TP upload, main-keep/service, shared KV), following `docs/`.
3. Generate the launchers with `launchers/make_dual_vision_launchers.py`, adjusting
   the paths at the top of the script to your machine, or write your own service
   config using the two JSONs as the reference parameter set.

## Reports filed upstream

- Full report to the fork: nicejunjie/Strata-rdna3#6
- Engine-level report to upstream: Niko1221/Strata#5480

## Credits and license

- Upstream engine: [Niko1221/Strata](https://github.com/Niko1221/Strata); RDNA3 fork:
  [nicejunjie/Strata-rdna3](https://github.com/nicejunjie/Strata-rdna3). This repo is
  an unofficial community fix/config pack, not affiliated with either author.
- The fixes were developed in a live debugging session (ChatGPT/Codex) on the repo
  owner's hardware, and were benchmarked and verified on that machine.
- Upstream license is MIT; the material in this repo is shared under MIT as well.

---

## 中文说明

在 Windows 上用 Strata 的 RDNA3 分支（nicejunjie/Strata-rdna3，基线提交 `bd34f079`）
把两张 RX 7900 XTX 跑成一个推理引擎的全部修复、配置与启动文件。

核心问题是 Windows HIP 的 `hipMemcpy2D`：以只读文件映射（GGUF 权重的映射方式）
为源做二维上传时，接口返回成功但数据静默传错，双卡、Gen3/Gen4 链路均复现，
模型加载后输出乱码。修复是加载期把列切片在 CPU 侧整理成连续缓冲、一次一维
上传（`STRATA_TP_UPLOAD_PACKED=1`），修复后 240 份切片回读逐字节一致。
另含三项修复：TP 提交期间主线程服务 CPU 专家请求、DP 长输入的主卡保留缓存
调度、DP foreign session 共享 owner 的固定页 KV（省 12.375 GiB 钉住内存）。

实测（精确 64K 输入 / 256 输出、无缓存、三跑中位数）：双卡 prefill 3589.2 /
decode 100.0 tok/s。交付两份带视觉的启动配置：256K（pin32）与 1M
（共享 KV 引擎、pin16 / reserve2048 / lend97，128K 输入已验）。

必须标明的边界：曾出现一次冷启动偶发错答、**根因未定位**（同配置此后 3+3 次
冷启动全过），故启动文件标为 Test；完整 1M 单次输入未验证，「1M」是配置上限，
最长已验单次输入为 261,888 token（256K 配置）与 131,072 token（1M 配置）。
细节见 `docs/` 四份报告。
