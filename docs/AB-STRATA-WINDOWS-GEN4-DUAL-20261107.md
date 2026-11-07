# Strata Windows 双 7900 XTX：M.2 Gen4 后的验证与常规调优

日期：2026-11-07。远程 Windows `<PC-LAN-IP>`，i9-13900KF、128GB DDR4、双 RX 7900 XTX 24GB，ASUS PRIME Z690-P D4。用户已装回主槽卡，外接卡继续使用 B / M.2_2 → OCuLink → DEG1。

## 当前交付结果

已保存桌面 `Strata-Dual7900-MTP-Vision-256K-Test.bat`、`Strata-Dual7900-MTP-Vision-1M-Test.bat`。二者视觉开启、保留 Strata Dashboard，监听 `0.0.0.0:8080`；一次启动一个。Dashboard：`http://<PC-LAN-IP>:8080/`；API：`http://<PC-LAN-IP>:8080/v1`。

- 256K 沿用原已通过的视觉版本，pin32 / reserve2560。
- 1M 采用共享 KV 修复引擎、pin16 / reserve2048 / lend97，保留 TP Decode 和 DP Prefill，自动分块恢复 32768。最终 live 冷启动、图片、中文、两次 64K 检索和一次 128K 检索全部正确；64K Prefill 3145.9、3191.5，128K 3449.6 / Decode 85.2。另一个独立同参数进程为 3141.0、3206.0、128K 3449.5 / 87.6。这些为功能请求计时，不是三轮同协议中位数。
- 锁定量逐档 12、16 通过，24 等待 600 秒失败，采用 16。共享 KV 初始化少申请约 12.375 GiB 固定页内存。原慢的 1M 分块配置约 2160–2175，最终约 3150–3200，提升约 46–48%；老主槽单卡 1M 本轮复核约 2955–2984。
- 完整 1M 输入尚未验证；此前 DP 偶发错答根因未彻底定位，故文件保留 Test。移除 TP 的对照发生错答，未采用。所有失败日志保留。本轮最终配置无新增显卡 WHEA / Display4101，不能据此宣称覆盖所有稳定性场景。

安装依据为每份配置和引擎的 SHA256 与实际 smoke / review 结果。测试服务已停止，用户可自行启动；完整历史与命令、源码差异、逐请求证据保存在下文及工作目录。

## 硬件与编号复核

装回主卡后 HIP 看到两张卡，当前顺序：

| HIP 编号 | 物理位置 | PCI bus | 固定页 H2D GB/s | 128 MiB 完整回读 |
|---|---|---|---:|---|
| 0 | M.2 / OCuLink 外接，SUBSYS 2422148C | 0000:07:00.0 | 6.991927 | 逐字节正确 |
| 1 | 主槽，SUBSYS 79011EAE | 0000:03:00.0 | 26.651654 | 逐字节正确 |

外接路径仍是 PCH 的 RP25 / PCI(1A00)，主槽是 CPU PEG1 / PCI(0100)。外接实测带宽仍符合 Gen4 ×4；不要将显卡内部端点的 ×16 属性写成外接通道 ×16。证据：`dual-m2-bandwidth-20261107.json`。双卡配置当前使用 `gpu=[1,0]`；换槽或改变设备数量后仍应重新核对编号。

## 统一测试条件

早期 Gen4 对照使用换槽前的独立 `engine-service\strata.exe`；本节参数仅对应早期 256K 基线。后续 1M 共享 KV 源码修复及最终配置见文末：

SHA256：`8f66abfe8d3c92693f8cdd73e4823d0d0a7fb03cbcbe4aa4f74deb6296268a52`。

- 模型：Qwen3.8-Flash-Next UD-IQ4_XS，模型及 pack 留在 `E:\Strata-0.1.13\Strata-data`。
- MTP spec=4、min-p=0.70、window=4096、zh60k draft vocab；完整路由 tail=0。
- 精确 65536 输入、256 输出，temperature=0、seed=42、关闭 thinking，无 prompt / conversation cache。
- Expert profile 每个测试从 `D:\strata-qwen224\era-route0-profile.bin` 独立复制，避免改写用户原 profile。
- VRAM reserve=2560 MiB、CPU expert workers=6、pcie-frac=0、expert arena pin cap=32 GiB。
- 保留已验证的 TP packed upload、coherent handshake 和 TP 提交期间服务 CPU 配置。
- `STRATA_VERIFY_SERVICE_DURING_LAUNCH=0`，未采用上轮失败的新增单卡提交候选。
- 不开发 DF2，不尝试用户提出的额外加权分块方法；本轮只验证原分支现有路径和参数。

## 主卡长输入配置与原双卡流水线

| 配置 | Prefill 中位数 tok/s | Decode 中位数 tok/s | 重复与检查 |
|---|---:|---:|---|
| 换槽前 Gen3 外接：主槽长 Prefill + 双卡 TP Decode | 2936.0 | 89.6 | 历史 `mtp-cache2560-64`，3 次 |
| 当前 Gen4 外接：同一主槽长 Prefill 配置 | 2990.2 | 96.0 | `mtp-m2-dual-keep64`，3 次全部通过 |
| 当前 Gen4 外接：原双卡 DP 长 Prefill + TP Decode | 3531.1 | 93.1 | `mtp-m2-dual-dp64`，3 次全部通过 |

当前主槽长输入配置的三轮 Prefill：2990.2、2994.6、2987.4；Decode：68.5、96.0、105.6。原双卡流水线三轮 Prefill：3545.7、3531.1、3522.2；Decode：70.7、93.1、116.6。两组均通过中文长回答、算术、多轮暗号以及三次长输入检索、精确输入 / 输出长度检查。

双卡流水线只把 `STRATA_DP_MAIN_ONLY=0`、`STRATA_DP_MAIN_KEEP_CACHE=0`，恢复原分支两张卡参与长输入的 DP 路径；仍保持 `STRATA_DP_FINAL_PUBLISH=0`。它相对当前主槽长输入的双卡配置，Prefill 提高约 **18.1%**。Decode 随专家缓存适应明显变化，不能只引用第三轮峰值。

旧 Gen3 原 DP 初筛的约 2421 tok/s 涉及早期配置，不作为本轮完全同参数的严格基线。当前双卡结果与此前主槽单卡 3281.2 / 53.9 的比较也先视为历史参考，待本轮主槽单卡校准补充。

## 原分支中短输入路径

`mtp-m2-dual-native-range`：8K、16K、64K 各一次全部正确，无 cache。8K / 16K 在原配置的 TP Prefill 范围内；64K 使用 DP 流水线。

| 输入 tokens | Prefill tok/s | Decode tok/s |
|---:|---:|---:|
| 8192 | 1215.2 | 75.8 |
| 16384 | 1851.0 | 101.9 |
| 65536 | 3551.2 | 99.1 |

不同长度不能只拿吞吐数字横比：启动开销、专家流入、缓存适应及实际 Prefill 路径不同。不得直接把 TP Prefill 的原上限强行扩到 64K / 400K，然后将未通过正确性的速度当作结果。

## 常规参数检查

基于原 DP 配置，每次均新服务进程、同 profile 来源、64K / 256：

| 参数变化 | Prefill tok/s | 检查 | 判断 |
|---|---:|---|---|
| MMQ tile row cap 64 → 128 | 3555.3 | 单次正确 | 收益约 0.7%，不足以认定优于基准 |
| 每 GPU stager threads 4 → 2 | 3578.2 | 单次正确 | 略快，待重复及长输入验证 |
| 每 GPU stager threads 4 → 8 | 3538.7 | 单次正确 | 没有明显收益 |

`probe_thread_affinity.py` 只读检查了模型线程：主提交线程和 4 个 stager 线程的 CPU mask 均为 `0xffffffff`，可使用全部 32 个逻辑核心；6 个 expert workers 分别在逻辑核心 2、4、6、8、10、12。没有发现搬运线程全部被限制在单核的情况。证据：`mtp-m2-stage2-thread-affinity.json`。

重复候选、长上下文 / 长输出验证、再次启动以及本轮主槽单卡对照完成后，在下方补充最终选定参数与结果。

## 每张卡 2 个搬运线程的重复验证

`mtp-m2-dp-stage2-validate64` 三轮全部正确：Prefill 3587.5、3589.2、3599.2，中位数 **3589.2 tok/s**；Decode 70.1、100.0、104.3，中位数 **100.0 tok/s**。另通过中文长回答、算术和中文多轮暗号检查。MMQ tile cap 保留 64。

相对默认 4 个搬运线程的同一原双卡 DP 配置，Prefill 约提高 1.6%；Decode 的约 7.4% 差异同时受生成内容与专家缓存适应影响，不应全部归因于搬运线程数。此配置正在做原参数不变的长输入 / 长输出与再次启动验证，尚未凭上述短测生成生产启动文件。

## Gen4 下复核原二维上传错误

`hip_copy_diagnostic.py` 通过 Python ctypes 直接调用当前 `engine-service\amdhip64_7.dll`，不经过 C++ 引擎的上传实现。两张卡分别比较普通 CPU 内存、只读文件映射偏移 256、固定页 CPU 内存的两个列半片，每片 8,355,840 bytes。

| 来源 / 方式 | 外接 Gen4 卡 | 主槽卡 |
|---|---|---|
| 普通 CPU 内存 → hipMemcpy2D | 两片均 0 bytes differ | 两片均 0 bytes differ |
| 只读 MapViewOfFile → hipMemcpy2D | 每片 8,323,025 bytes differ | 每片 8,323,025 bytes differ |
| 固定页 CPU 内存 → hipMemcpy2D | 两片均 0 bytes differ | 两片均 0 bytes differ |
| CPU 整理为连续片 → hipMemcpy | 所有来源的两片均 0 bytes differ | 所有来源的两片均 0 bytes differ |

二维接口未报错但只读映射的数据不正确；连续整理后上传全部正确。此错误在 Gen4 外接和 CPU 主槽都复现，因此不能只归因于旧 Gen3 链路或转接卡；不经过 C++ 编译的直接调用也复现，支持问题出在当前 HIP / Windows 映射内存上传路径。尚不能仅凭此测试细分到底是 runtime、驱动还是系统内部的哪一个组件。

原 TP packed upload 修复在 Gen4 下仍有必要，予以保留；不要与上一轮未通过正确性的新增单卡异步提交候选混为一谈。证据：`hip-copy-gen4-diagnostic.json`；复现输入：`hip-2d-source-gen4.bin`；命令参数保存在本轮脚本 / 记录中。

## 保存位置与边界

远端完整工作目录：`D:\codex-work\strata-win-20261107`；本报告同名副本保留到 Windows 用户桌面。本地也保存结果副本。每个测试前缀对应 `*.json` 配置、`*.summary.json`、逐请求 `*.result.json`、engine / server 日志。

前一轮单独外接卡的记录见 `AB-STRATA-WINDOWS-M2-AFTER-20261107.md`：原 fork Gen4 ×4 单卡 2267.0 / 42.9，原桌面 DF2 单次 2219.7 / 41.6；没有原桌面 BAT 在旧 Gen3 外接路径的严格结果。

此阶段的测试上限为 262144；后续已增加 1M 上限配置及实际 128K 检索验证，仍未完成 400K / 700K / 完整 1M 输入验证。首次外接单卡预热卡住在后续单卡验证中未再复现，其根因仍未完全定位；本轮双卡正确通过不能把它改写成“已彻底修复”。新增单卡异步提交候选仍不采用；Gen4 也不是删除 TP 列切片上传修复的证据。

## 最终验证发现的错答：暂不生成生产启动文件

同一 stage2 配置的 `mtp-m2-stage2-final-stress` 正确通过 64K、128K、4K、8K，均精确生成 1024 tokens；并通过中文、算术、多轮暗号。64K 3585.7 / 93.1，128K 3814.8 / 101.7，4K 907.1 / 99.4，8K 1228.7 / 103.3。

但随后新引擎进程 `mtp-m2-stage2-final-cold64` 的首个 64K / 256 请求未找回暗号，回答把仓库记录误说成编程片段；输入与输出长度正确。此轮 3515.8 / 86.4 仅是失败请求计时，不作为有效性能。预热冰箱回答正确，随后长输入错答，尚未定位最终根因。验证流程已停止，主槽单卡校准尚未执行，生产 BAT 尚未生成。

此前的 3589.2 / 100.0 和三轮正确记录保留，但不能宣称此配置已稳定通过所有验证。需要先处理偶发正确性问题，再决定最终采用的方案。

### 硬件日志核对

本次 Windows 开机以来只有一条相关 WHEA-Logger 17 纠错记录，时间 2026-11-07 14:07:52 +08:00，根端口 00:1c.2 / DEV_7ABA。其子设备确认是 Realtek Gaming 2.5GbE Family Controller / DEV_8125；外接 GPU 根端口是 00:1a.0。因此不能把这条网卡端口记录当作 OCuLink 错答的证据。没有查到本次开机以来的显卡 Display 4101 / 对应驱动重置记录，两张显卡 PNP 状态均 OK。

`gen4-system-events-before-stress.json` 保存日志。180 秒双卡并行固定页 H2D / D2H 已完成，每轮动态填充 64 MiB 数据及序号，并完整回读比较。外接卡 3480 轮、233,538,846,720 bytes 回读检查全部正确；主槽卡 5236 轮、351,382,011,904 bytes 回读检查全部正确。测试后没有新增 WHEA / Display 4101，仍只有上述网卡根口记录。结果：`gen4-transfer-stress-180s.json`、`gen4-system-events-after-stress.json`。

该检查只覆盖持续传输，不完全等价于模型计算 / mapped handshake 的负载，不能宣称彻底排除链路。但 PCIe 通常会通过 CRC 检测和重传处理传输错误，链路异常更常见的可观测后果是降速、硬件错误、超时或掉卡；当前没有取得与错答对应的显卡链路错误证据。

### 冷启动复查

保持相同 r0 长输入、独立 profile 副本、64K / 256，追加六个独立服务进程：

| 配置 | 三次 Prefill tok/s | 三次 Decode tok/s | 检查 |
|---|---|---|---|
| 原 stage2，early TP=1 | 3585.1、3594.6、3568.6 | 74.7、74.1、74.4 | 三次全部正确 |
| 仅 early TP=0 | 3578.9、3578.5、3571.5 | 71.9、72.5、72.1 | 三次全部正确 |

加上此前 `mtp-m2-stage2-final-cold64` 的一次错答，原参数仍存在一条明确的失败记录。关闭 early TP 的三次通过不足以证明它修复了问题，因为原参数同样三次通过，且开关的性能差别很小。因此不采纳未经因果验证的新开关，保持原配置；偶发错答根因未定位。证据：`gen4-cold-controls.json` 及 `mtp-m2-cold-repeat-[abc]`、`mtp-m2-earlytp-off-cold-[abc]` 完整记录。

## 用户要求的双卡视觉启动文件

读取旧桌面 `Qwen-EraRoute0-256K.bat`、`Qwen-EraRoute0-1M.bat`，确认它们通过老 control CLI 启动单卡配置，监听 `0.0.0.0:8080`；旧 profile 含 `--vision` 和 GPU / CPU reader、mmproj、视觉 tokens 上限 768。

新增独立双卡 MTP 测试启动文件，不覆盖旧 BAT / profile：

- `Strata-Dual7900-MTP-Vision-256K-Test.bat`
- `Strata-Dual7900-MTP-Vision-1M-Test.bat`

配置从本轮 stage2 参数复制，保留完整路由、双卡 TP 和原长输入 DP，分别 `--max-context 262144`、`1048576`；加上旧视觉配置和 `--vision`。256K 保持已通过的 `engine-service` / pin32；1M 改用下文共享 KV 申请修复的 `engine-shared-kv` / pin16。两者共用 `0.0.0.0:8080`，一次只启动一个。Strata 网页 Dashboard：`http://<PC-LAN-IP>:8080/`；API：`http://<PC-LAN-IP>:8080/v1`。网页来自原项目 `serve/web/index.html`，页面标题 Strata。

这些启动文件标为 Test，因为本轮 DP 偶发错答的根因尚未定位，不能宣传为彻底修复后的稳定生产方案。各自专家 profile 为独立副本，保存在工作目录；旧 profile 不改写。生成与安装脚本：`make_dual_vision_launchers.py`；实际服务验证：`check_dual_vision_launch.py`。

### 256K 视觉启动与边界验证

实际启动后 `/health` 报告 max_context=262144、images=true、loaded=true。首个 64K / 256 暗号检索正确（3476.1 / 59.5），输入图片后正确识别从左到右的红色正方形、蓝色圆形、黄色三角形；随后中文首都回答正确。图片之后再次 64K / 256 检索正确（3537.1 / 92.7）。视觉 reader 常驻占用显存，不能把这些配置的单次速度与未开启视觉的中位数直接混为同一协议。

接近容量上限的输入为 261888 tokens，三个暗号全部找回，输出 248 tokens。初版测试器误按请求的 256 输出判失败，后来核对源码确认 `serve/server.py` 的 `CTX_SLACK=8`，`Service.prepare()` 会把输出缩为 `max_context - prompt_tokens - 8`；引擎同样要求 `n + max_new + 8 <= max_context`。248 tokens 是文档化边界行为，不是此次偶发错答。

保留原始 `dual7900-mtp-vision-256k-test.smoke.json`（初版判定 false）及逐请求记录，没有删除失败记录；`review_vision_context_slack.py` 只复核该计数预期，另存 `dual7900-mtp-vision-256k-test.smoke.review.json`。该容量结果不当作精确 256 输出协议的性能数据。

### 1M 配置启动问题与内存上限

直接沿用 256K 参数、仅扩大 max-context 的双卡 1M 配置，在专家缓存初始化前报 `CUDA1 free memory: unspecified launch failure`，继而显示 0.00 GiB / no room。这个 0.00 是错误后的查询结果，不能证明物理显存真的用满了。

以下对照均保存独立配置、summary 和 engine 日志：

| 1M 变化 | 结果 |
|---|---|
| 原参数，专家 arena pin=32 GiB、显存 reserve=2560 MiB | 初始化失败 |
| 仅 pin=16 GiB | 相同初始化失败 |
| 回到 pin32，仅 reserve=4096 MiB | 相同初始化失败 |
| 回到原参数，仅 TP_SHARE_DP=0 | 相同初始化失败 |
| 回到原参数，仅 DP_PREFILL=0 | 相同初始化失败 |
| 移除 TP 参数，保留两张卡和 DP | 相同初始化失败 |
| 使用旧单卡 BAT 的基础参数 + 双卡 TP 及必要上传 / handshake 修复，pin32 | 相同初始化失败 |
| 回到原参数，仅 pin=8 GiB | 启动、图片、中文、两次 64K / 256 全部通过 |
| 原参数，pin=12 GiB、reserve=2560 MiB | 已完成权重 / 缓存分配，但 600 秒仍未 READY，检查超时 |

另一次用 `--tensor-parallel 0` 的尝试只触发参数帮助，未进入初始化，不算有效硬件 / 内存对照；关闭 TP 应移除该参数，已随后按正确方式验证。

pin8 的实际 API 报告 max_context=1048576、images=true、loaded=true。图像正确识别红色正方形、蓝色圆形、黄色三角形；图片后中文回答正确。两次 64K / 256 检索均找回全部暗号，Prefill 2119.3、2128.8；Decode 46.2、62.6。只是功能检查的两次计时，不宣称完整性能中位数。

源码 `generate-main-keep.cpp` 的 arena_src 分支明确为 Windows / WDDM 双卡默认 8 GiB 锁定保护：大量 host pages 映射到两张卡后，WDDM 可能拒绝后续分配。约 55.43 GiB 的专家数据仍在 RAM 中；pin8 是其中直接注册 / 映射给 GPU 的部分，其他仍可经过固定页 staging ring 上传。128 GiB RAM 容量与可同时锁定 / 映射给 GPU 的额度是不同限制。

pin12 等待时进程 CPU 用时保持 47.609375 秒不变，私有内存约 120.2 GiB，Windows 虚拟内存尚余约 13 GiB、物理 RAM 尚余约 19 GiB。不是仍在持续读取模型。保存 `dual7900-mtp-vision-1m-pin12-startup.dmp`（MINIDUMP_NORMAL，仅线程栈 / 模块、302187 bytes）。栈中包含 AMD HIP runtime、rocBLAS 和 Strata 地址；简单地址扫描不是完整堆栈展开，不能单凭它定位具体错误函数。

当前证据支持这个启动问题与大上下文下的 host pin / GPU 映射资源条件有关，不能据此宣布 Windows / HIP 的内部具体根因已彻底确认，也不能自动将它等同于此前那次偶发错答。原引擎 pin12、仅增大显存 reserve=4096 MiB 的复核同样 600 秒未 READY，已保存独立失败记录 `dual7900-mtp-vision-1m-pin12-reserve4096.*`。

1M 上限的完整长输入质量 / 稳定性尚未验证，不能将“配置为 1M”写成“已通过完整 1M 推理”。视觉功能和 64K 检查与完整百万 token 输入是不同验证范围。

### 局域网与 Dashboard 实测

从当前 Mac 实际请求 `http://<PC-LAN-IP>:8080/health`，返回 1M、images=true、loaded=true；请求 `/` 返回 HTTP 200、17227 bytes HTML，页面标题 Strata。服务监听 0.0.0.0:8080，与旧 BAT 相同，现有 8080 防火墙规则可以访问，不需新增规则。证据：服务 health / models 结果，Dashboard 页面本地副本。

启动与视觉测试后再次查系统日志，仍仅有开机初那条 Realtek 网卡根口的 WHEA 17，没有新增显卡 WHEA / Display 4101。结果：`gen4-system-events-after-vision.json`。

## DP foreign session 的重复固定页 KV 申请修复

源码确认 `generate-main-keep.cpp` 的 DP foreign session 先调用 `session_init()`，其中 `qsa_state_init()` 为每个 QSA 层申请完整固定页 host KV。调用返回后，DP 路径又直接把 `.host` 替换为该层 owner session 已有的 KV；因此先申请的那份不再被这条路径使用，仍占着全局 allocator / runtime 的固定页资源。

独立候选 `engine-shared-kv\strata.exe` 通过新 helper 让 full-geometry DP foreign session 在初始化时直接借用 owner 的 host KV，跳过这笔重复申请。校验 owner 的层范围、上下文长度、页面数量、KV 模式 / 格式 / 指针；原函数签名保留 wrapper，其他调用路径沿用原行为。TP 半头 session 的布局不同，仍保持原分配方式。原工程、原 `engine-service` 和已通过的 256K 视觉配置未覆盖。

新引擎 1M 日志记录 12 次 `avoided 1107297280 bytes`，共 **13,287,567,360 bytes / 12.375011 GiB** 的多余固定页申请被跳过，DP prompt path 仍开启。这是运行时实际数值，修正早期约 6.19 GiB 的估计。它确认消除了资源浪费；不能据此认定此前所有驱动故障或偶发错答均由它造成。

构建使用原 ninja 命令的相同编译参数，独立编译 layer / session / generate 三个对象，连接已有 packed TP upload、coherent verifier 和 Prefill 修复对象。源码与完整 diff：`make_shared_kv.py`、`layer-shared-kv.cpp`、`session-shared-kv.cpp`、`generate-shared-kv.cpp`、`shared-kv.patch`；构建命令 / 日志 / SHA256 保存在 `build_shared_kv.py` 和 `shared-kv-build-manifest.json`。

按用户要求执行 12 → 16 → 24 GiB，只有上一档实际启动、两次 64K / 256 暗号检索、图片、中文全部正确才继续。显存 reserve 保持原 2560 MiB；每档从同一个旧桌面 expert profile 重新复制，避免前一档的学习直接影响后一档。

| 共享 KV 修复版，1M 上限、视觉开启 | 首次 64K Prefill / Decode | 图片后 64K Prefill / Decode | 功能检查 |
|---|---|---|---|
| pin12 GiB | 2134.2 / 46.7 | 2152.2 / 66.6 | 全部通过 |
| pin16 GiB | 2153.5 / 48.2 | 2175.5 / 64.2 | 全部通过 |
| pin24 GiB | 未开始推理 | 未开始推理 | 600 秒未 READY，超时失败 |

以上为每档两次功能请求的计时，不是多轮统计中位数。12 与 16 的 Prefill 差异约 1%，不能宣称扩大锁定量带来很大收益。12 / 16 分别在约 53.2 / 56.2 秒 READY；24 总计约 603.5 秒后判超时，未开始推理，不记录为有效性能。24 期间 CPU 用时保持 44.65625 秒，物理可用内存约 32 GiB、commit 可用约 25 GiB。保存 `dual7900-mtp-vision-1m-shared-pin24-startup.dmp`（307495 bytes，仅线程栈 / 模块），不能把它简单写成 RAM 用满。完整逐档记录：`shared-kv-ladder.summary.json`。

最终 1M Test 配置选择 pin16，显存 reserve 保持 2560 MiB。原 1M pin12 / reserve4096 的 live 配置及日志完整复制到 `archive-1m-original-pin12-reserve4096`，所有独立试验文件仍保留。新引擎 SHA256：`f916b44e3bd65d568720a444a6103a527d304a5bbbc11f64818d61c3759732cc`。

### 同条件的上下文容量对照

为避免将 pin32 的 256K 与 pin16 的 1M 混成单变量对照，追加 `check_vision_matched_context.py`：同一个共享 KV 修复引擎、pin16、reserve2560、双卡、视觉、MTP、同一旧 expert profile 来源、同一个 64K / 256 输入，仅 max-context 不同。两种上限均正确通过图片、中文和两次暗号检索。

| 相同 pin16 和引擎 | 首次 64K Prefill / Decode | 图片后 64K Prefill / Decode |
|---|---|---|
| 256K 上限 | 3310.6 / 57.4 | 3370.9 / 85.8 |
| 1M 上限 | 2153.5 / 48.2 | 2175.5 / 64.2 |

1M 容量下同样 64K 输入的 Prefill 低约 35%，不是在说百万 token 的输入已经测试。每张 GPU 启动后的专家缓存约减少 1.9 GiB，分块上限从 32768 降为 29440。源码 `Prefill::take_stage()` 按 session 的全部 n_pages 分配 KV staging pool，`Prefill::carve()` 按 max_cells 定义索引工作区；多个 SessionState 的 RoPE / 索引状态也按上下文上限分配。这些是固定容量预留影响缓存的直接证据；不能凭日志将全部降幅精确分摊到某一缓冲。

另核对 `qsa_select.cu`，HIP prompt 的 score / top-k 路径已经使用 active_blocks 限制实际范围，因此未实施“把上限范围扫描改成实际范围”的猜测性改动。容量对照使用同一链路，没有对应显卡 WHEA / 掉卡证据，不能将这个确定性的容量降速归因于 Gen4 协商。

独立 256K 容量对照保留在 `dual7900-mtp-vision-256k-shared-pin16-matched.*`。桌面 256K 文件继续沿用原 pin32 已通过版本，约 3476–3537 tok/s 的视觉检查结果不替换为 pin16 对照。

### 首次 1M live 配置验证（reserve2560，现已归档）

`dual7900-mtp-vision-1m-test.json` 已切换为共享 KV 修复引擎 / pin16，profile 与引擎日志使用独立 live 路径。再次真实启动后正确通过 64K / 256（2164.2 / 48.5）、图片、中文、第二次 64K / 256（2174.7 / 63.6），并追加精确 131072 / 256 检索全部暗号正确（2722.0 / 74.1）。所有请求无缓存复用。结果保存在 `dual7900-mtp-vision-1m-test.smoke.json` 及逐请求文件。

配置上限 1M；当前 live 配置最长实际输入验证为 128K，完整百万输入仍未验证。不能用 128K 的吞吐宣称百万输入速度。

## 主槽单卡与双卡的资源效率复核

用户指出整机 RAM 仍为 128 GiB，显存新增 24 GiB，因此不能将双卡慢于老单卡解释成“容量增加自然要慢”。据此运行 `compare_1m_resource_paths.py`，每个进程都使用相同旧 expert profile 来源、同一 64K / 256 输入、视觉开启、上下文上限 1M；单卡强制原始 HIP device1（03:00.0 / 主槽），避免误测外接卡。

| 配置 | 首次 64K Prefill / Decode | 图片后 64K Prefill / Decode | 正确性 |
|---|---|---|---|
| 老桌面配置，主槽单卡 | 2955.4 / 53.7 | 2983.5 / 60.2 | 全部通过 |
| 本轮共享 KV 修复引擎，主槽单卡、pin16 | 2656.6 / 38.4 | 2671.1 / 49.7 | 全部通过 |
| 本轮双卡 TP + DP，pin16 / reserve2560 | 2164.2 / 48.5 | 2174.7 / 63.6 | 全部通过 |
| 本轮双卡 DP，移除 Decode TP 参数 | 不作为有效速度 | 未继续 | 首个长输入错答，仅输出 web_search 工具调用，没有暗号，停止 |

旧配置的 JSON 此时实际含 `--mtp`，旧 BAT 的 DFlash2 文字不是判断本次实际草稿器的依据。老配置 tail skip=7、pcie-frac=0.20、expert arena 全注册；本轮 full route=0、pcie-frac=0、pin16 及多个 fork 开关不同，因此老/新单卡不是仅改可执行文件的单变量比较。它复现了用户所述约 3000 的老单卡速度，且同一 fork 的单卡也比原双卡 1M 配置快。

移除 TP 的首个请求输入计数正确，但输出仅 15 tokens 的 `<tool_call><function=web_search>`，并非预期 256 tokens / 三个暗号；其计时保留在原始结果中，不能作为成功的速度数据，也不采用这个配置。所有记录：`vision-1m-resource-paths.summary.json` 及 `vision-1m-resource-*`。

### 分块阈值及保留 TP 的参数修复

`generate-main-keep.cpp::dp_step_for()` 和 `Prefill::run_dp()` 要求平衡的偶数块。以 65536 输入为例：容量为 32768 时是 2 × 32768；容量降为 29440 后 `ceil(65536/29440)=3` 再补为偶数 4，变成 4 × 16384。实际服务的首尾少量模板 / checkpoint 片段不改变这个阈值结论。四块路径多做专家搬运和跨卡状态发布，较小的 GEMM 批次也影响效率。这是明显的分块跳变，不能只按分块上限减少约 10% 来估计耗时。

保持所有 TP、完整路由、共享 KV、pin16 参数，仅把显存 reserve 从 2560 调为 1536 MiB，独立测试 `check_1m_chunk_headroom.py`。实际 auto chunk 恢复为 32768；两次 64K 检索、图片、中文和 128K 检索全部正确。

| 双卡 TP + DP，1M 上限 | 首次 64K Prefill / Decode | 图片后 64K Prefill / Decode | 128K Prefill / Decode |
|---|---|---|---|
| reserve2560，lend93 | 2164.2 / 48.5 | 2174.7 / 63.6 | 2722.0 / 74.1 |
| reserve1536，lend93 | 3192.9 / 53.2 | 3231.1 / 75.4 | 3480.5 / 86.2 |

64K Prefill 提高约 48%，并已超过刚复测的老单卡；128K 提高约 28%。降低 reserve 同时增加了缓存和跨过分块阈值，所以不能把全部增益精确归到其中一项。此结果证明“1M 双卡一定低于老单卡”是错误结论，当前分支的分配 / 分块参数对速度影响很大。

reserve1536 的实际全部加载后 GPU0 / GPU1 可用显存为 1415 / 532 MiB，属于较紧的外卡余量。因此继续复核 reserve2048 / lend97 是否能同样保留 32768 chunk，给外卡更多余量；该后续结果见下文。

### 最终采用 reserve2048 / lend97

`check_1m_balanced_headroom.py` 的独立候选正确通过冷 64K（3141.0 / 51.7）、图片、中文、第二次 64K（3206.0 / 76.7）、128K（3449.5 / 87.6）。于是选择同参数写入 live 配置，再按真实 BAT 将引用的配置独立启动：冷 64K（3145.9 / 51.9）、图片、中文、第二次 64K（3191.5 / 69.2）、128K（3449.6 / 85.2）全部正确。所有长输入计数精确、输出 256 tokens、无 cache、找回全部暗号。

最终实际 auto chunk=32768，全部加载后 GPU0 / GPU1 可用显存 **1927 / 1042 MiB**。相比 reserve1536，Prefill 略慢但外卡余量多约 510 MiB，因此采用这组通过的配置。源配置：`dual7900-mtp-vision-1m-tp-reserve2048-lend97.json`；live 配置：`dual7900-mtp-vision-1m-test.json`；最终结果：`dual7900-mtp-vision-1m-test.smoke.json`。先前 live 的 reserve2560 版本全部文件 / 请求保存到 `archive-1m-shared-pin16-reserve2560`，原失败版保留在 `archive-1m-original-pin12-reserve4096`。

`make_dual_vision_launchers.py --install` 已验证两份配置与引擎 SHA256，实际复制两份 BAT 到 `C:\Users\<YOUR_USER>\Desktop`；文件长度 256K=980 bytes、1M=975 bytes。安装清单：`dual-vision-launchers-manifest.json`；使用原 Strata 网页和 8080 监听，无需其它 Dashboard。最终服务 PID3888 已由测试器只清理自己的 PID 树，未留运行服务。

测试后 `gen4-system-events-after-shared-final.json` 中两张 7900 XTX 状态 OK / code0，没有新增显卡 WHEA / Display4101；仍只有早期开机时 Realtek 网卡根口 00:1c.2 的那条 WHEA17。此前偶发错答和完整 1M 输入验证仍为开放项，因此仍明确标注 Test。
