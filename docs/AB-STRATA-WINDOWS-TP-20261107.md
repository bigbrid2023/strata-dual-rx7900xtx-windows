# Windows 双 RX 7900 XTX：Strata 修复与验证

更新日期：2026-11-07。权重上传错误已定位，基础修复通过；长上下文验证和性能调优仍在进行。

## 环境与范围

- Windows 主机 <PC-LAN-IP>；i9-13900KF、128 GB DDR4、双 RX 7900 XTX 24 GB。
- 主板 PRIME Z690-P D4，主卡 Gen4 ×16，OCuLink 外接卡 Gen3 ×4，无 GPU P2P。
- 模型 Qwen3.8-Flash-Next UD-IQ4_XS，原分支 HEAD bd34f079da92e8b47dc4de6b40d894a867154797。
- 原工程 `D:\anan-work\Strata-rdna3-fixed`，原引擎 `engine-fixed\strata.exe`。
- 实验目录 `D:\codex-work\strata-win-20261107`；测试端口 18107，仅本机访问。
- 原工程、原引擎、原 profile 均保留。每个实验复制独立 profile，以免请求结束后的自动保存污染对照。

## 已确认的错误与修复

原 TP2 路径通过 `hipMemcpy2D` 将 GGUF 权重按列切片上传。接口返回成功，但第一层 `blk.0.ssm_out.weight` 的 GPU 回读与正确切片比较：

```text
8273507 / 8355840 bytes differ
first mismatch offset = 0
expected byte = 244
actual byte = 69
packed = 0
```

这发生于模型加载阶段。它是实际模型数据错误，不是终端中文显示编码问题。

修复候选先在 CPU 内按正确列顺序整理成连续缓冲区，再用一次 `hipMemcpy` 上传，避开二维复制。

```text
STRATA_TP_UPLOAD_PACKED=1
```

候选引擎 `engine-upload\strata.exe`。逐字节诊断可另开 `STRATA_TP_UPLOAD_CHECK=1`；正常使用和测速关闭诊断。

修复版检查了两卡的 96 份列切片，全部 0 bytes differ；英文 READY、中文“中国的首都是北京”、算术 17-5+3=15 三题全部正确。原版同配置输出实际重复乱码，关闭 megakernel 仍一样。

独立 Python ctypes 直接调用相同的 HIP DLL，绕开 Strata 的 C++ 编译，也复现了错误：普通可写主机内存、hipHostMalloc 固定页内存的二维复制正确；只读 Windows 文件映射（MapViewOfFile、FILE_MAP_READ）作为源时，两卡均有 8323025 / 8355840 字节不同，且 API 返回成功。对应连续整理上传全部正确。这将问题进一步缩小到该 Windows HIP 运行库处理只读文件映射的二维复制路径。尚未通过更换 HIP 版本或阅读运行库内部完成归因；不能断言 Windows 系统、编译器或驱动整体有错。

复现脚本和结果：`hip_copy_diagnostic.py`、`hip-copy-diagnostic.json`。原引擎与桌面老版引擎的 amdhip64_7.dll SHA256 相同：344386DD39B2BBA7060D62720054B9375401F23F2BCD29D730DD8D43019683CD。

整理和上传只在模型加载时进行；Prefill/Decode 使用已驻留显存的权重，不在每个推理步骤重新整理。启动耗时增量尚未做严格对照。

## 定位证据

完整模型第一层逐步对比，单卡与两卡按正确头映射抽取的半布局：输入 token、embedding、residual、mixed input、Q/K/V 投影、conv、gate、beta、z、递推 y 和相关参数全部零差异。第一层输出投影后才开始偏离，相对 RMS 误差约 1.3889。

完整模型首个窗口的 96 次双卡 all-reduce：两卡结果逐位相同，且逐位等于两卡输入的 FP32 和；没有 nonfinite。这不支持用“两张卡链路速度不同导致计算失步”解释本次乱码。

原始诊断：

- `dense-tp-first.dense-compare.json`：第一层细分比较。
- `thread-first.analysis.json`、`thread-first.single-compare.json`：交换及单卡/双卡比较。
- `packed-upload.engine.log`、`packed-upload.smoke.json`、`packed-upload-*.raw.json`：修复后的字节检查与真实 API 回答。
- `single-current.smoke.json`：当前 Windows 单卡三题正确。

## 必须撤销的旧解释

旧独立交换探针使用 GPU `clock64()` 设置内部等待期限，但尚未证明该计时在这台机器上可靠；它们的“超时/旧数据”不能作为模型乱码的根因证据。旧无期限探针确有外部超时，也不能覆盖上述完整模型实测。

独立 coherent mapped memory 两卡读写正确。固定计算量并发测试单卡约 47 ms，两卡一起仍约 47 ms，输出零差异，说明此 Windows 环境可以双 GPU 并发计算。

带快照诊断的 GraphLaunch 在两个 host threads 提交后可以运行，但它本身没有修复乱码；不是最终修复方案。

## 构建与复现

- `tp-upload.cpp`：独立修复源码；只修改列切片上传分支。
- `build_tp_upload.py`、`build-tp-upload.cmd`：沿用原 Ninja 编译/链接参数，只重编译独立 tp.cpp 对象，在原库前链接。
- `tp-upload.build.log`、`tp-upload-link.build.log`、`tp-upload-link.command.txt`：编译及链接证据。
- DLL 从原引擎复制到新 exe 旁边，保证使用相同的 HIP 运行库；原构建产物不覆盖。
- `run_model_case.py`：基础三题验证，保存原始 API JSON。
- `run_windows_bench.py`、`generate_exact_prompts.py`：Windows 启停服务，使用项目 `rdna3/bench.py` 的标准输入和请求协议。

## 进行中的长上下文与性能测试

正式性能比较使用精确 65536 输入 / 256 输出、三次重复、无 prompt cache、temperature 0、seed 42、关闭 thinking。所有三处密码必须检索正确、输入计数精确、输出长度达到要求，才计入通过。再验证 64K/1024、128K/1024 的持续生成。

长中文、数学、多轮对话及精确 4K、8K、64K 输入的三处密码检索均通过。默认修复双卡 64K/256 三次中位数 Prefill 2247.8、Decode 81.5 tok/s（各次 Decode 49.3、81.5、89.5）。它还不是最终优化结果。

必须纠正早先的单卡对照：`current-single64` 使用的是删掉 TP 的双卡配置，且选择 GPU 0。独立测量证明 Windows 当前的 HIP GPU 0 是外接卡（PCI bus 0000:09:00.0，128 MiB 固定页上传中位数 3.512 GB/s）；GPU 1 是主板卡（PCI bus 0000:03:00.0，25.9996 GB/s）。因此 1558.7 / 33.2 tok/s 只能作为“外接单卡 + 分支配置”的诊断结果，不能代表用户桌面 BAT 或主板单卡的性能。主板单卡对照正在重测。

桌面 BAT 指向 `D:\strata-qwen224\profile-qwen0156df2-era-route0[-256k].json`，实际老版引擎 SHA256 E41EE2F4D220704C94487B663FE1F60852437BC99619F53D4D2E7F810186CAF9。其专家 profile、CPU 工作者、PCIe 分担、Prefill ring、尾部路由跳过与原双卡配置不同。用户已有 MTP/DF2 对照，认为两者速度接近，DF2 用于节省内存；不能把草稿器差别直接当作速度差异的主因。

独立复制的桌面配置未明确选卡时在 Prefill 主机缓冲区分配处失败，DF2 自动退回 MTP 后仍失败；相同 CLI 启动也复现。明确选主板 GPU 1 后，原桌面参数成功运行并实际启用 DF2。

正确的桌面主板单卡对照 `desktop-main64`：精确 64K 输入 / 256 输出三次全部通过，Prefill 分别 3320.2、3334.4、3325.8，中位数 **3325.8 tok/s**；Decode 分别 55.7、63.9、63.7，中位数 **63.7 tok/s**。这支持用户桌面单卡接近 3000 tok/s 的观测。用户日常的 70+ Decode 使用不同输入和生成长度，不能直接当作本协议的数据。

DF2 文件已确认：`E:\Strata-0.1.13\Strata-data\dflash2\qwen3.8-flash-next-dflash2.q4_0.pack`，522,458,112 字节，同目录有 `draft_vocab.bin`。当前 fork 的 `src/program/generate.cpp` 明确限制 DF2 仅单卡 CLI，不能用于该 build 的 serve/batch/multi-GPU；老普通引擎能服务 DF2。现阶段双 TP 测试实际使用 MTP，不能仅加入 DF2 参数就宣称已经使用 DF2。

`STRATA_ROUTE_TAIL_SKIP=7` 会略过某些所有窗口 token 都排在 rank 7 及以后的未驻留专家，是近似路由；并不是跳过最后 7 层。桌面方案开启了它，原双卡配置关闭。后续分别记录默认完整路由和沿用桌面近似设置的结果，不将速度改善视为无输出代价。

“主板卡长输入 Prefill + 双 TP Decode”初筛 `packed-mainpf32` 正确通过：2542.4 / 53.4 tok/s；只移用桌面 CPU 6 工作者、CPU share 0.6/max 5120、ring 192 的 `packed-maincpu32`：2527.9 / 55.0 tok/s，未确认收益。扩大 DP 批次的 `packed-mainchunk32` 在首个验证窗口失败，没有有效性能数据。当前正在验证省去闲置外接卡的缓存借出/回填，以及仅在末个输入批次交接最终状态的独立 opt-in 候选。

固定页上限 16/32 GiB 的首次双卡筛选约 2358/2411 tok/s Prefill，都是单次筛选。DP_SHARE 与关闭 DP 的候选在首个 verify 窗口失败；全部保留失败记录，未选作最终配置。独立两线程提交候选仍需验证收益。尚无最终性能结论。

日后换 M.2 OCuLink 转接后沿用本次最终引擎、配置和相同输入复测，核对实际负载下链路速率并比较正确性和速度。

## 后续调优记录（尚未选定最终启动方案）

独立缓存候选 `engine-main-keep`，SHA256 5e2524342eae8ecd130fd13dda327d8381af59f086b06249e6b9d5d373bcdcf8：主板卡承担长输入 DP，全程保留闲置外接卡的专家缓存，只在末个输入批次交接各层最终状态和完整 QSA 索引前缀；短请求、TP Prefill、分段/恢复路径保留原缓存布局。

`main-keep32`、`main-keep-era32` 未通过首次短窗口；`dual-era32`、`dual-era-pcie32` 则通过 64K/256 单次检查，速度 2444.3/59.0、2413.9/57.5。后一项只额外将 PCIe 分担设为 0.20，没有确认收益。这些试验含诊断 trace，属于初筛。

明确使用 coherent 主机通知内存的 `main-coherent32` 仍停在首个窗口，不能宣称这个开关独自解决了启动问题。该次 GPU breadcrumbs 已达到第一层 VRAM hits，CPU trace 只有 WINDOW、尚无 LAUNCHED，CPU 工作者没有接到任务。它支持“提交尚未返回时 GPU 已等待 CPU 工作”的判断，不说明 HIP 内部为什么会等待。`main-coherent-era32` 与关闭 megakernel 的 `main-nomk-era32` 单次正确通过，分别 2955.6/58.7、2954.8/60.9；不能把一次成功等同于冷启动稳定。

新独立候选 `engine-service`（SHA256 8f66abfe8d3c92693f8cdd73e4823d0d0a7fb03cbcbe4aa4f74deb6296268a52）新增 `STRATA_TP_SERVICE_DURING_LAUNCH=1`：两卡提交期间主线程即可服务 CPU 专家请求，服务完再等提交线程；提交未返回时不通过 stream query 把尚未入队误认成已经完成。原同步提交和旧双提交线程路径均保留。`service-smoke` 的英文 READY、中文首都、算术全部通过。

`service-era64` 精确 64K/256 三次全部通过，Prefill 2953.9、2973.3、2965.2，中位数 **2965.2 tok/s**；Decode 62.2、88.5、101.7，中位数 **88.5 tok/s**。初次回答与后续回答差距较大，不能只取最快的 101.7 来承诺实际速度。这个配置沿用桌面近似路由 tail=7、YaRN scale=4 和原用户专家 profile，实际草稿器为 MTP；仍慢于桌面单卡 DF2 的 3325.8 Prefill，但本协议下 Decode 高于其 63.7 中位数。完整路由、多次冷启动、长输出和矩阵批次的进一步对照仍在进行。

MMQ row cap 改为 0（不限制）或 128 的两项单次筛选正确通过，分别 2948.0/61.5、2951.0/62.0，与 cap 64 没有确认收益，未选择这些变化。开启 megakernel 的 `service-mk64` 虽能启动，但 64K 请求未找回三处密码，只生成 218 tokens 并返回与问题无关的工具调用文本；它未过正确性检查，不能把 2909.6/58.1 当有效性能。最终候选保留 megakernel 关闭。

关闭近似路由的 `service-full64` 首次 64K/256 也未找回密码，回答误述了输入内容。尚未定位是模型/参数组合还是额外加速路径的影响，不能将完整路由配置作为验证通过的生产版本。长输出和启动产物的最终验证暂缓，正在以老版单卡 DF2 的相同完整路由请求作对照，并检查双卡额外加速组合。

完整路由后续对照：老版主板单卡 DF2 `desktop-full64` 的相同 64K/256 请求正确通过（3342.4/52.4，单次）；双卡将 combine_cpu、wait_fuse、verify_qdedup、tp_alias_map 同时关闭的 `service-full-safe64` 正确通过（2932.6/55.7）。单独关闭 verify_qdedup 的 `service-full-noqdedup64` 正确通过（2962.2/58.9），单独关闭 tp_alias_map 的 `service-full-noalias64` 也正确通过（2940.2/55.5）。这说明现有加速组合下的正确性需要继续验证，尚不足以独立归因到某个内核内部错误。正在以 verify_qdedup=0 进行三次完整路由、长输出及重复启动验证；所有失败记录保留。

随后相同 verify_qdedup=0 配置的冷启动 `service-full-final64` 在第一个 64K 请求仍失败：输入精确，但只生成 232 tokens，返回与原问题无关的 Python 代码。因此撤销“单独关闭量化重用就足够修复”的推断；尚未生成任何新的生产启动 BAT。

扩大上传诊断后，`upload-all-check` 使用独立 `engine-upload-all`、关闭 alias map、保留原行切片直传，检查 **144 份行切片 + 96 份列切片，合计 240 份全部 0 bytes differ**，英文/中文/算术通过。这个冷启动的行切片直传没有复现数据错误；没有证据要求额外启用 row_packed。源码和回读日志保留。正在分开验证原 DP、主卡 DP 和减少缓存/状态复制的路径，避免将一次成功当成根因或稳定性结论。

用户已要求暂停继续 DF2。DF2 仅保留路径和已完成的单卡对照，后续工作集中于双卡 MTP 正确性和性能。

## MTP 分步隔离：保留缓存，撤掉最终状态集中发布

同一个 `engine-service`、完整路由、关闭 combine_cpu/wait_fuse/verify_qdedup/alias_map 的冷启动初筛：原 DP `full-pure-dp64` 正确通过 2421.4/56.1；主板卡 DP、仍按原方式借出/回填缓存和逐批发布状态的 `full-main-original64` 正确通过 2515.9/56.2；保留闲置外接卡缓存、仍逐批发布状态的 `full-main-keep-no-final64` 正确通过 2944.8/56.5。以上都是单次结果。

随后 `mtp-keep-steady64` 三次 64K/256 全部通过，Prefill 2944.0、2935.5、2936.8，中位数 **2936.8 tok/s**；Decode 55.8、83.3、86.7，中位数 **83.3 tok/s**。候选保持 `STRATA_DP_MAIN_ONLY=1`、`STRATA_DP_MAIN_KEEP_CACHE=1`、`STRATA_DP_FINAL_PUBLISH=0`。末次集中发布状态没有显示额外性能收益，先撤掉它；尚未用重复诊断证明它是此前间歇内容错误的独立根因。正在验证该保守组合的长输出、128K 输入、长短切换和冷启动，尚未包装生产 BAT。

`mtp-keep-stress` 已通过长中文、算术、多轮暗号，以及 64K、128K、4K、8K 输入各持续生成 1024 token。64K 为 2933.3/76.5，128K 为 2903.4/84.5；随后短输入仍正确（4K 611.3/80.0，8K 727.4/90.0）。另一次冷启动 `mtp-keep-cold64` 正确通过 2911.6/56.9。此处证明的是这些请求和启动检查通过，未覆盖 700K 或 1M。

MTP 参数对照（各 64K/256 三次全部正确）：预留显存从 3072 降到 2560 MiB 的 `mtp-cache2560-64` 中位数 2936.0/89.6；spec=6、min-p=0.5 的 `mtp-spec6-64` 2926.1/76.3，无性能收益；恢复 CPU combine/wait fuse 的 `mtp-cpu-fuse64` 2929.6/83.3，无确认收益。先保留 spec=4、min-p=0.70 和保守 CPU 设置。

## Prefill 没有双卡增益：当前证据和边界

必须明确：主板卡长输入候选的约 2900 tok/s **不是两张卡并行 Prefill 的速度**。它是在这台机器原双卡路径偏慢后，保留主板卡处理长输入、双 TP Decode 的保守调度。用户对 Prefill 仍没有双卡增益的判断成立。

同一个独立引擎、MTP、model/profile、量化、输入和其他相同参数的主板单卡 `mtp-matched-main64` 三次全部通过：Prefill 3252.2、3292.0、3281.2，中位数 **3281.2**；Decode 53.9、53.5、56.4，中位数 **53.9**。对应双卡 2936.0/89.6，即 Prefill 约慢 10.5%，Decode 约快 66.2%。不能拿旧 DF2 与新 MTP 的差别解释这一组同配置对照。

分支 `rdna3/reference.json` 的 IQ4 参考确有大幅增益：64K 单卡 3549.5/95.7，双卡 7230.3/123.8；128K 单卡 3480.2/91.9，双卡 7082.3/126.8。参考平台为 9950X3D2、128GB DDR5、Linux、两卡各 PCIe 4.0×8。其 64K 长输入走原 DP 分块流水线；TP Prefill 原配置只接约 5K–18K，不能混为一条路径。

`mtp-keep-profile64` 的真实阶段测量（诊断开启，单次速度不作最终中位数）：主板卡 65529 个主体输入 token，GPU timeline 20775 ms，wall 20812 ms。等待专家复制 3069 ms（14.8%）；专家 gate/up GEMM 2792 ms（13.4%）、down GEMM 2166 ms（10.4%）；HC read 2143 ms（10.3%）、QSA select 2186 ms（10.5%），其余为 GDN、注意力、路由、合并等。两批累计专家流入 46868 次（26436 次直接来自固定页 arena），显存驻留命中仅 2284 次，CPU 专家计算 0 次。Prefill 借槽占用工作区，专家缓存被大量挤出；这条大输入路径的直接瓶颈不是 CPU 专家计算。日志的 host staging 时间与 GPU 工作重叠，不能与 GPU timeline 相加。

强行将 TP Prefill 的 MAX 扩到 1M、在 64K 用原 18432 上限分成约 16K 的块：`mtp-tp-long-profile64` 未通过，第一次 Decode 已产生 non-finite logits，两次请求重试后报 NaN。两卡 GPU wall 约 48.7 秒；外接卡 wait copy 约 11.8 秒，主板卡 combine 阶段约 16.3 秒（含等待另一卡）。这超出原配置所测的 TP 单块范围，不能用其失败速度作为正确双卡性能。正在回到原长输入 DP 路径验证专家共享上传和固定页内存条件。

后续三项诊断候选均未产生有效性能：`mtp-dp-share-profile64`（DP_SHARE=1、ring=320）实际启用了 DP share，但首个长输入报 `experts_native_f16: invalid resource handle`；`mtp-dp-pin64-profile64` 完整固定页 arena（55.43 GiB）在另一卡专家缓存初始化时出现 `fill_slot_blocking: unspecified launch failure`；随后 `mtp-tp-original-profile16` 模型初始化等待超过外部 420 秒限时。诊断版存在额外计时钩子，尚未排除诊断代码或资源状态对这些失败的影响，不将它们归因为某个确定的硬件/驱动缺陷。实验进程已清理，未查到残留实验进程或最近对应的系统 Display/WHEA 超时记录；注册表 TdrDelay=20，未改动。

已准备、但**尚未编译或验证**的 `prefill-weighted.cpp` / `prefill-weighted.patch` 只为 TP Prefill 新增 `STRATA_TP_PREFILL_NR0`，按显式比例把两卡都未驻留的专家分配到 rank 0，已驻留专家仍在其所在卡计算，默认保留原行为。这只是后续链路不对称调度的源码候选，不能当作有效优化或启动产物。

用户提出：同参数复测 OCuLink 单卡若仍明显偏慢，就先暂停软件优化，改用 M.2 转接卡争取 Gen4×4。当前正在运行 `mtp-matched-external64`：与 `mtp-matched-main64` 相同引擎、MTP 和其他配置，只切换物理 GPU 0（外接卡），精确 64K/256、三次重复。之后保留当前证据，优先做链路 A/B；暂停 DF2 的要求持续有效。

用户的具体换卡计划：CPU 直连 M.2 槽位于主板主卡下面，因此拆下主板卡，安装 M.2→OCuLink 卡后，先只通过外接 7900 XTX 启动 Windows。i9-13900KF 没有核显，显示器接外接卡；显卡坞先上电再冷启动。先核对实际 PCIe Gen4×4，再测外接单卡，同一张卡、同线、同坞、同显卡 BIOS 档位。单卡首次检查通过后再装回主板卡，复测双卡。拆主卡会改变 HIP 可见设备与序号，不能沿用今天双卡的 GPU 编号或把双 TP 配置原样用于仅一张卡。

外接单卡同参第一轮已正确通过：64K/256，Prefill **1435.8**、Decode **29.3**，没有 prompt cache。待剩余两轮结束后保存最终中位数，并按用户要求暂停软件调优。

## 本轮结束状态：按用户要求暂停软件调优，等待 M.2 转接验证

`mtp-matched-external64` 三轮全部正确：Prefill 1435.8、1440.8、1437.8，中位数 **1437.8 tok/s**；Decode 29.3、31.0、33.7，中位数 **31.0 tok/s**。相同引擎和 MTP 配置的主板单卡为 **3281.2/53.9**；外接单卡 Prefill 只有主板卡约 **43.8%**。这是当前外接路径显著限制吞吐的直接对照，但不能单凭它定位到某一个转接芯片、线缆或驱动组件。

软件调优现已按用户要求暂停；DF2 也仍暂停。不生成未经完整检查的新的生产启动 BAT。本轮实际使用的候选 exe、源码、独立 profile、配置、日志和逐请求结果均留在 `D:\codex-work\strata-win-20261107`。已验证的保守长输入组合为 `engine-service` + `mtp-keep-steady64.json`（3072 MiB 预留，已过 64K 三次、128K/1024、长短切换、中文/数学/多轮及冷启动）；2560 MiB 预留的 `mtp-cache2560-64.json` 三次 64K/256 正确，Decode 中位数 89.6，但尚未完成同配置长输出和 128K 验证。

换 M.2 后先只装外接卡：重新读取 HIP 设备数量、PCI 总线和实际负载下链路，确认 Gen4×4，创建独立单卡配置，不保留 `--tensor-parallel 2` 或双卡 layer_split。复用同引擎、相同 MTP 与 expert profile 来源、精确 64K/256 协议。先比较 Gen3/Gen4 的外接单卡结果，主板卡装回后再测试原双卡 DP 与当前保守候选；不能只以开机识别或空闲时显示的链路代替负载检查。

CPU 直连 M.2 的 Gen4×4 理论单向带宽约 7.9 GB/s，仍只有分支参考机每卡 Gen4×8 的一半；期待改善有依据，不能承诺直接复现参考的约 7230 tok/s。当前未覆盖 700K/1M 长会话。

## M.2 Gen4 外接单卡后续验证

2026-11-07 实际使用 B / M.2_2，仍为 PCH 路径，已协商 Gen4 ×4；128 MiB 固定页 H2D 实测 6.981 GB/s，完整回读正确。原桌面 DF2 的 64K / 256 单次 2219.7 / 41.6 正确；换槽前原 fork MTP 同协议三次中位数 2267.0 / 42.9，中文 / 算术 / 多轮均通过，再次启动 2260.6 / 39.4 也通过。旧 Gen3 外接的同 fork MTP 基线为 1437.8 / 31.0，改善约 57.7% / 38.4%。

第一次原 fork 在短输入预热卡住，后续未再复现；新增单卡异步提交候选完成请求却未通过暗号检索，明确不采用。不能据此把旧问题全部归因到 Gen3 转接卡，或宣称旧 TP 列切片上传修复在 Gen4 有害。原工程、桌面 BAT 和既有配置保留。具体证据与失败记录索引见 `AB-STRATA-WINDOWS-M2-AFTER-20261107.md`；本轮服务已结束，下一步装回主卡再测 Gen4 双卡。
