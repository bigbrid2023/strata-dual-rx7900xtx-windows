# M.2 → OCuLink Gen4 外接单卡验证

日期：2026-11-07。Windows `<PC-LAN-IP>`，i9-13900KF、128GB DDR4、RX 7900 XTX 24GB，ASUS PRIME Z690-P D4。用户已拆下主槽显卡，只安装原外接撼讯卡，并将 PCIe → OCuLink 转接卡换为 M.2 → OCuLink。FurMark2 已停止后进行本轮测试。

## 链路与显卡身份

- HIP 只看到一张物理 GPU，编号 0，PCI bus `0000:04:00.0`；显卡 SUBSYS `2422148C`，驱动 `32.0.32015.7029`。GameViewer 虚拟显示设备不计入 HIP 显卡数。
- 用户确认负载下为 Gen4 ×4。固定页 128 MiB 连续 H2D 上传，排除首轮后五次中位数 **6.981162 GB/s**；128 MiB 完整回读逐字节正确。换槽前约 **3.512 GB/s**，上传带宽约翻倍。
- 当前 Windows 设备链为 Intel `DEV_7AC8` 根口 `PCIROOT(0)#PCI(1A00)` / `ACPI(RP25)` → AMD 1478 → AMD 1479 → GPU 744C。这仍是 PCH 路径，与用户使用 B / M.2_2 槽一致，并非 CPU 直连 M.2_1。
- GPU 端点的内部 Gen4 ×16 属性不能当作整条外接通道的宽度；外接通道按 Gen4 ×4 记录。

## 原桌面 BAT 配置：一次数据记录

原 BAT：`C:\Users\<YOUR_USER>\Desktop\Qwen-EraRoute0-256K.bat`。其原命令使用 control 0.1.56 的 `strata.py serve --profile qwen0156df2-era-route0-256k`。本轮复制该配置到独立文件，仅选择当前 GPU 0，并按统一协议禁用 conversation cache；不覆盖原 BAT 或原 profile。

实际启动日志确认为 **DFlash2 alone**，并非 fork MTP。原 exe：

`C:\Users\<YOUR_USER>\AppData\Local\Strata\components\engine\0.1.56-windows-x86_64-hip-rdna3\strata.exe`

SHA256：`e41ee2f4d220704c94487b663fe1f60852437bc99619f53d4d2e7f810186caf9`。

Qwen3.8-Flash-Next UD-IQ4_XS，精确 65536 输入、256 输出，无 prompt cache，temperature=0、seed=42、关闭 thinking，profile 从 `D:\strata-qwen224\era-route0-profile.bin` 独立复制。

| 接法 | Prefill tok/s | Decode tok/s | 重复数 | 检查 |
|---|---:|---:|---:|---|
| 此前主槽单卡 `desktop-main64` | 3325.8 | 63.7 | 3，中位数 | 全部通过 |
| 当前 Gen4 ×4 外接 `desktop-m2-gen4-single64` | 2219.7 | 41.6 | 1 | 三处暗号、精确输入与输出长度均通过 |

本次外接单次结果相对主槽中位数，Prefill 低约 33.3%、Decode 低约 34.7%。**没有原桌面 BAT 在旧 Gen3 外接路径上的严格结果**，不能把旧 fork 的 1437.8 当成这个 BAT 的 Gen3 基线。

## 换槽前原 fork MTP：重复验证

复用换槽前 `engine-service\strata.exe`，SHA256：

`8f66abfe8d3c92693f8cdd73e4823d0d0a7fb03cbcbe4aa4f74deb6296268a52`

基于 `mtp-matched-external64.json`，只选 GPU 0，去掉 TP / layer split；没有启用新增单卡提交修复。完整路由 tail=0、MTP spec=4 / min-p=0.70 / window=4096、zh60k draft vocab、VRAM reserve=2560 MiB、CPU workers=6、pcie-frac=0、expert arena pin cap=32 GiB。其余参数和 profile 来源保持换槽前基线。

| 接法 | Prefill 中位数 tok/s | Decode 中位数 tok/s | 结果前缀 |
|---|---:|---:|---|
| 此前主槽单卡 | 3281.2 | 53.9 | `mtp-matched-main64` |
| 此前 Gen3 ×4 外接单卡 | 1437.8 | 31.0 | `mtp-matched-external64` |
| 当前 Gen4 ×4 外接单卡 | 2267.0 | 42.9 | `mtp-m2-original-validate64` |

当前三轮 Prefill：2259.3、2267.9、2267.0；Decode：36.8、42.9、45.2。三轮均通过精确输入、输出长度、三处暗号检查。另通过中文长回答、算术及中文多轮暗号检查。

相对旧外接接法，当前 Prefill 提高约 **57.7%**、Decode 提高约 **38.4%**；相对主槽单卡，仍分别低约 30.9%、20.4%。这是实际更换接法后的比较：转接卡、速率、在机显卡数量以及显示输出所在 GPU 同时变化，不能将全部差异单独归因于 PCIe 代数。

随后再次独立启动同一原 exe，`mtp-m2-original-cold64` READY 37.625 秒，50-token / 128-output 预热及 64K / 256 请求均通过；Prefill **2260.6**、Decode **39.4**，三处暗号正确。这里的冷启动指新服务 / 引擎进程，不是 Windows 重启或断电冷启动。这轮没有再次复现首次预热卡住。

## 首次卡住与新增候选：未采用

1. `mtp-m2-gen4-single64`：同一原 fork 程序首次启动 READY 约 37.1 秒，但在 50-token / 128-output 预热窗口卡住，没有进入 64K 测试。GPU rang=1，CPU served / plan / copies 均为 0，6 个 CPU workers 全部 sleeping；约 60 秒 watchdog 收集 dump 后报告 #267。此轮没有有效 Prefill / Decode。
2. 基于该迹象生成单卡异步提交候选 `engine-single-service\strata.exe`，仅由 `STRATA_VERIFY_SERVICE_DURING_LAUNCH=1` 开启。SHA256：`dbfbc4abe7409c21e10abe5f5cae2247d3fdba1a30aaa648606c7230e66424da`。独立编译，不覆盖原工程或生产启动文件。
3. `mtp-m2-single-service64`，开关=1：通过预热并完成 64K 请求，但回答没有检索到暗号，内容与实际问题不符。虽记录了 2187.2 / 49.6 的计时，**正确性检查失败，不算有效性能，也不采用此候选**。
4. `mtp-m2-single-service-off64`，同一候选 exe、开关=0：64K 请求正确通过，2262.0 / 38.1，单次。随后回到原 exe 的三轮验证也全部通过。因此不能说此开关已定位或修复首次卡住。

首次卡住时保留的 dump `strata-stall-28600.dmp` 有 HIP / DXCore 等待迹象。使用简单栈内地址扫描只能作辅助，不是完整符号化调用栈；不能仅凭它把具体 API、Windows、驱动或编译方式定为根因。目前卡住未在上述后续验证中再次出现，仍记录为未完全定位的偶发提交 / 同步问题。

## 对“旧修复是否在 Gen4 变成问题”的结论

- Gen3 / 转接路径此前确实限制性能，现在更换接法后上传带宽和实际吞吐都提高。
- 之前 Windows HIP 只读 MapViewOfFile 上的二维 TP 列切片上传错误，已用绕开 C++ 编译的独立调用复现，并用连续整理后上传修复；它不依赖“必须是 Gen3”这个条件。当前单卡不进入 TP 列切片上传路径，本轮不能证明该修复在 Gen4 有害，也不能证明双卡时可以删除它。
- 此次新增单卡异步提交候选没有通过正确性检查，明确暂不采用；旧修复与这个新候选须分别判断。
- 当前原桌面和原 fork 都已得到正确的 Gen4 外接单卡结果。双卡收益须在装回主卡后实际验证，吞吐不是两张卡各自速度的算术平均。

## 保存与继续测试

远端工作目录：`D:\codex-work\strata-win-20261107`。本报告同名副本保留在 Windows 用户桌面。本地也有原始结果副本。

- `m2-bandwidth-20261107.json`：带宽与完整回读结果。
- `desktop-m2-gen4-single64.{json,summary.json}`、逐请求 `*.result.json`：原桌面单次结果。
- `mtp-m2-original-validate64.{json,summary.json}`、逐请求 / extended `*.json`：原 fork 三次及内容检查。
- `mtp-m2-original-cold64.*`：再次启动的独立验证记录，2260.6 / 39.4，检查通过。
- `mtp-m2-gen4-single64.*`：首次卡住的失败记录。
- `mtp-m2-single-service64.*`、`mtp-m2-single-service-off64.*`：新增候选开关对照及失败回答。
- `verify-single-service.cpp`、`single-service-during-launch.patch`、构建脚本及 `engine-single-service`：未采用候选，供后续分析；不要用开关=1作为日常启动方案。

保持原桌面 BAT 和换槽前原 fork 配置。装回主卡后必须重新核对 HIP GPU 编号和物理接法，再用同模型 / profile / 输入协议复测单卡及双卡。当前没有 Gen4 双卡结果；也没有本轮 700K / 1M 验证。

本轮所有测试服务已结束。可以按用户原计划关机、装回主槽显卡；首次偶发卡住仍没有充分证据落实到一个最终根因，不能宣称已彻底修复。
