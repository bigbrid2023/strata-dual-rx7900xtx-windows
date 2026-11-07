# Windows 双 7900 XTX：排查方法、修复原理与模型调优学习笔记

整理日期：2026-11-07。本文汇总这次 Windows 实测与前期硬件排查，供以后研究 Maya 的 GLM5.3 Flash、Strata 的 DS v4.1 Flash 时参考。后两者是用户计划测试的项目／模型名称，本文没有验证它们的具体版本、兼容性或性能。

本文区分“已经用数据确认的错误”“有效的绕行修复”“通过了部分验证的配置”和“仍未定位的现象”。有可运行的方案，不代表全部偶发问题已经彻底消失。

## 1. 当前可以运行什么

Windows 主机为 `<PC-LAN-IP>`，i9-13900KF、128 GB DDR4、ASUS PRIME Z690-P D4、两张 RX 7900 XTX 24 GB。模型为 Qwen3.8 Flash Next UD-IQ4_XS，本轮最终双卡草稿器是 MTP。

桌面启动文件：

- `Strata-Dual7900-MTP-Vision-256K-Test.bat`
- `Strata-Dual7900-MTP-Vision-1M-Test.bat`

两者都带视觉和 Strata 自带 Dashboard，监听 `0.0.0.0:8080`，一次启动一个。

| 用途 | 地址 |
|---|---|
| 本机 Dashboard | http://127.0.0.1:8080/ |
| 局域网 Dashboard | http://<PC-LAN-IP>:8080/ |
| 局域网 API | http://<PC-LAN-IP>:8080/v1 |

1M 文件设置的是 **1,048,576 tokens 的容量上限**；自动测试实际最长输入为 **131,072 tokens**。完整百万输入、长期真实会话质量仍需要后续验证，所以名字保留 Test。

### 最终配置及验证范围

| 项目 | 256K 文件 | 1M 文件 |
|---|---|---|
| 引擎目录 | `engine-service` | `engine-shared-kv` |
| 上限 | 262144 | 1048576 |
| 专家 arena 注册上限 | 32 GiB | 16 GiB |
| 显存 reserve | 2560 MiB | 2048 MiB |
| Prefill lend 比例 | 93% | 97% |
| 自动分块上限 | 32768 | 32768 |
| 实际最长输入检查 | 261888，边界输出248 | 131072，输出256 |
| 视觉 | 开启 | 开启 |
| Decode / 长输入 Prefill | TP / DP | TP / DP |

两份配置保留完整路由 `STRATA_ROUTE_TAIL_SKIP=0`、MTP spec4 / min-p0.70 / window4096、6个 CPU expert workers、每卡2个 stager threads、KV int8 / resident32768；双卡配置使用原始 HIP 编号 `gpu=[1,0]` 和手动 `layer_split="24"`。更换插槽、设备数量或驱动后，应重新核对编号。

最终 1M live 文件一次独立启动的有效结果：

| 请求 | Prefill tok/s | Decode tok/s | 检查 |
|---|---:|---:|---|
| 首个64K / 256输出 | 3145.9 | 51.9 | 三个暗号正确，计数精确，无缓存 |
| 图片后64K / 256输出 | 3191.5 | 69.2 | 同上 |
| 128K / 256输出 | 3449.6 | 85.2 | 同上 |

同参数另一个独立进程：64K为3141.0、3206.0，128K为3449.5 / 87.6；图像和中文均正确。这些是功能请求计时，不能当成三轮同协议中位数。

## 2. 先把现象分成不同层次

本次经历了几个不同问题，不能用一个“驱动问题”概括全部。

| 现象 | 首先检查 | 本次得到的结论 |
|---|---|---|
| 开机黑屏、设备完全不枚举 | BIOS、供电时序、转接路径、PCIe速率 | 原PCIe转接路径接7900只能稳定Gen3；换M.2路径后实际Gen4工作 |
| 设备出现又消失、桥设备报31/45/10/28 | 设备是否持续存在、GPU端点、链路训练 | 桥设备出现不代表GPU已完整枚举，错误码变化不能直接归因到AMD显示驱动 |
| 模型输出重复乱码 | 原始API内容、权重回读、单卡/双卡中间值 | 确认TP列切片上传的数据已错误；与终端编码无关 |
| 预热／首个窗口卡住 | CPU/GPU等待关系、任务提交是否返回 | 双卡路径增加“提交期间服务CPU任务”的绕行修复；另一次单卡卡住仍未完全定位 |
| 1M初始化失败／无READY | 注册内存、重复KV申请、显存、commit、线程是否前进 | 去掉约12.38GiB多余固定页申请后12/16GiB档通过；24仍超时 |
| 能正确运行但Prefill很慢 | 实际分块、缓存借出、复制等待、参数与对照条件 | 1M配置跨过分块阈值，64K从2块变4块；调整reserve/lend后速度恢复 |
| 偶发长输入错答 | 保存完整失败请求和冷启动记录 | 尚未完全定位；不能用后来的几次通过抹去失败 |

排查顺序是：**设备持续可用 → 数据正确 → 提交／同步能前进 → 内存分配可持续 → 正确性重复通过 → 性能调优**。模型已经读入错误权重时，任何吞吐数据都没有优化意义。

## 3. 硬件／OCuLink是怎么排查的

### 3.1 前期观察与BIOS定位

用户前期实测：5060 Ti可在DEG1使用；7900 XTX拨到另一档显卡双BIOS后能在395小主机使用。台式机打开 Above 4G Decoding、暂时关闭 ReBAR 后能进入系统；后来发现先前改的是主卡插槽速率，改到真正接OCuLink转接卡的插槽并限制Gen3后，7900可以工作。

这些步骤解决的是启动／枚举条件。不要据此推断 ReBAR 必须永久关闭，或者某个驱动重装可以替代链路训练检查。5060 Ti曾在节能降速后恢复Gen4时掉卡，关闭PCIe链路节能有帮助；这是用户对该路径的观察，不能自动推导所有显卡都需要同样设置。

换用M.2→OCuLink卡后，外接7900实际协商到Gen4×4，用户先单卡运行Furmark，再做软件测试，然后装回主卡复测双卡。

单卡压力测试通过，说明该负载下没有明显掉卡；它不验证文件映射上传、模型权重、mapped-memory握手或所有双卡负载。

### 3.2 用物理位置识别显卡，不凭GPU编号猜

最终装回主卡后的实测：

| 原始HIP编号 | PCI bus | 接法 | 固定页128MiB H2D |
|---|---|---|---:|
| 0 | `0000:07:00.0` | B / M.2_2 → OCuLink → DEG1 | 6.99 GB/s |
| 1 | `0000:03:00.0` | CPU主槽 | 26.65 GB/s |

外接路径此时是PCH的RP25 / `00:1a.0`，并未因为换成M.2卡就变成CPU直连。主槽是CPU PEG1。原始HIP device1经过 `gpu=[1,0]` 的可见设备重排后，日志可以显示为CUDA0；日志里的“CUDA”也是这套跨平台代码的命名，不代表实际用了NVIDIA卡。

早期外卡曾是 `09:00.0`。拆卡、换槽后GPU编号和bus都可能改变。本次曾把外接GPU0误当主槽单卡，得到过低的“单卡”对照，后来通过PCI bus与上传带宽纠正。

7900 XTX本身为PCIe4设备；主板插槽支持Gen5，不代表它在跑Gen5。显卡内部端点显示×16，也不代表OCuLink上游通道变成×16。

### 3.3 同时测带宽、完整回读和系统事件

更换接法前，同配置外卡单卡64K的Prefill中位数1437.8、Decode31.0；换M.2后的外卡为2267.0 / 42.9，主槽为3281.2 / 53.9。这证明接法改善有实质收益，但换卡、速率、显示输出、设备数量同时变化，不能将全部收益单独归到“Gen3→Gen4”。

双卡并发固定页H2D/D2H持续180秒，每轮写不同序号和动态内容、完整回读64MiB：外卡3480轮，主卡5236轮，均正确。最终没有新增显卡WHEA或Display4101。

唯一WHEA17是开机时Realtek网卡根口 `00:1c.2 / DEV_7ABA`，外卡根口为 `00:1a.0`。**有一条PCIe错误日志，必须先查它属于哪个根口及子设备。**

证据文件：`dual-m2-bandwidth-20261107.json`、`gen4-transfer-stress-180s.json`、`gen4-system-events-after-shared-final.json`。

这些证据缩小了链路故障的可能性，但没有覆盖所有推理负载。不同PCIe带宽会增加等待，不会天然使两张GPU“不同步”；正确实现应通过事件、队列和协议保持依赖关系。

## 4. 乱码的根因：API成功，权重却已经复制错

### 4.1 先区分显示编码与模型数据错误

终端乱码时，应保存HTTP响应的原始UTF-8 JSON并直接查看模型 `content`。若只是终端显示错误，可检查UTF-8环境；若保存下来的内容也重复、混乱，或者英文/算术同样错误，就继续查模型数据。

本次原双卡输出的错误存在于实际API回答。单卡英文、中文、算术正确。关闭megakernel没有修复乱码。

### 4.2 从第一个偏离的位置向前追

对同一输入检查单卡与双卡的正确布局映射：embedding、residual、Q/K/V、conv、gate、beta、递推y等一致；第一层输出投影后才偏离，相对RMS误差约1.3889。

同时检查首个窗口96次all-reduce，两卡结果相同，并等于两卡输入的FP32和，没有非有限值。这说明不能跳过权重检查，直接把乱码归到跨卡交换。

逐字节回读 `blk.0.ssm_out.weight` 的列切片，原版约8.27百万 / 8.36百万字节不同。权重在模型加载时已经错误，后续运行不崩溃也会回答错误。

### 4.3 把问题从Strata抽成最小HIP复现

`hip_copy_diagnostic.py` 用Python ctypes直接调用同一个 `amdhip64_7.dll`，绕开Strata C++编译。固定同一随机数据、行距和两份列切片，分别使用不同CPU来源上传，再完整回读。

| 来源／上传 | 二维hipMemcpy2D | CPU整理连续后hipMemcpy |
|---|---|---|
| 普通可写CPU内存 | 正确 | 正确 |
| 固定页CPU内存 | 正确 | 正确 |
| 只读MapViewOfFile，偏移256 | 两卡均大量字节不同，API仍成功 | 正确 |

Gen4时再次复现：每份8,355,840字节，二维上传有8,323,025字节不同；连续上传0字节不同。主槽和外卡都能复现。

定位结果是：**当前Windows HIP运行库处理这类只读文件映射二维上传的路径有实际数据错误。** 尚未通过更换运行库版本或内部调试区分runtime、驱动、系统内部具体责任。不能据此说所有Windows复制、所有AMD驱动或编译器都有错。

### 4.4 最终采用的上传修复

TP按列切片时，在CPU逐行提取正确列范围、拼成连续缓冲，再进行一维上传。该整理发生在模型加载阶段，普通Prefill/Decode不会每个token重新整理权重。

```text
STRATA_TP_UPLOAD_PACKED=1
```

修复后的两卡96份列切片逐字节正确；扩大检查后144份行切片＋96份列切片，共240份正确。没有证据要求把所有行上传也强制改成packed，额外row_packed未采用。

文件：`tp-upload.cpp`、`fix-windows-tp-upload.patch`、`build_tp_upload.py`、`hip_copy_diagnostic.py`、`hip-copy-gen4-diagnostic.json`。

学习重点：**检查返回码之外，还要检查结果数据；从首次分歧层定位；用最小复现剥离引擎与编译因素。**

## 5. 首个窗口卡住：看清谁在等谁

模型图里的GPU可以等待CPU专家计算。Windows HIP的某次GraphLaunch尚未返回时，GPU可能已经执行到这个等待点；若主线程一直等提交返回，再去服务CPU任务，就会形成等待环。

现场线索是：GPU breadcrumbs已到第一层等待／VRAM hits，CPU日志仍只有WINDOW，没有LAUNCHED，worker没有接到任务。

双卡修复让各GPU在提交线程里启动图，主线程立刻服务CPU请求，服务结束后再等待提交线程返回；提交尚未返回期间，避免把stream query误判为工作已完成。

```text
STRATA_VERIFY_COHERENT=1
STRATA_TP_SERVICE_DURING_LAUNCH=1
STRATA_TP_LAUNCH_THREADS=1
```

coherent通知内存和提交期间服务CPU是不同环节，单独切到coherent没有证明能修复所有卡住。修复文件为 `verify-service.cpp`、`service-during-launch.patch`、`build_verify_service.py`。

另一次Gen4外接**单卡**预热卡住没有充分定位。新增单卡异步提交候选虽然能越过卡点，却发生长输入错答，因此未采用：

```text
STRATA_VERIFY_SERVICE_DURING_LAUNCH=0
```

还撤销了早期用GPU `clock64()` 超时探针直接归因的解释，因为其计时可靠性未证实。线程dump中的HIP/DXCore地址也是线索，简单栈内地址扫描不等于完整符号化调用栈。

有效修复应建立在“等待关系证据＋对照＋重复正确性”上。一次开关后不再卡，不足以确认因果。

## 6. 128GB RAM够，为什么1M仍会卡在初始化

### 6.1 分开看四种额度

| 额度 | 意义 |
|---|---|
| 物理RAM | 实际CPU内存容量，可放模型、专家、KV和系统工作集 |
| Windows commit | 系统对已提交虚拟内存的承诺额度，通常由RAM和页文件共同支撑 |
| 固定页／注册内存 | 被锁定、注册或映射给GPU的CPU页面；除了物理容量，还受驱动及映射资源条件影响 |
| 每张GPU显存 | 各卡独立的权重、KV、索引、工作区和专家缓存 |

`STRATA_ARENA_PIN_GIB=16` 限制的是专家arena的直接注册部分，不是让整个程序只能使用16GB RAM。约55.43GiB的专家数据仍可放在RAM，未注册部分经固定页staging上传。VirtualLock工作集锁定量也不能直接等同于cudaHostRegister量。

两张24GB卡提供总计48GB容量，但当前实现并没有一个单卡式的48GB连续显存池。双卡有额外TP状态、各卡工作区和必要复制，RAM总容量保持128GB时，程序的资源需求仍可能增加。

### 6.2 逐档测试，不用“还有空闲”代替验证

原1M配置pin32、pin16、增大reserve、关闭DP、移除TP等早期对照都曾失败。出现 `unspecified launch failure` 后读到“free=0”，不能把这个错误后的查询值当成显存真的耗尽。

原引擎pin12在reserve2560／4096下均等600秒无READY，CPU用时保持不变。它已经不是持续加载文件的状态。保存了配置、engine日志、summary和仅含线程／模块的minidump，没有依靠猜测重装Windows。

### 6.3 源码发现一份申请后马上被替换的KV

原DP foreign session的初始化过程：

```text
session_init()
  → qsa_state_init()
  → 为foreign层申请完整的固定页host KV
初始化返回
  → foreign.host = owner.host
```

后一步已经改用owner已有的KV，前一步申请的那份在这条路径上不再使用，但仍占固定页资源。

独立修复新增共享KV初始化helper：直接借用owner.host，不做这笔重复申请。校验层范围、max_cells、页数、KV模式／格式和指针；保留原函数签名供其他路径使用。

TP半头KV与全头布局不同，不能把它也随手替换为同一指针。此次只改full-geometry DP foreign路径，避免“共享内存”导致布局错误。

1M实际日志为12次 `avoided 1107297280 bytes`，合计 **13,287,567,360 bytes，即12.375011GiB**，修正了先前6.19GiB的估计。DP仍正常开启。

| 去掉重复申请后的pin档位 | 结果 |
|---|---|
| 12GiB | 约53秒READY，64K两次、图片、中文全部正确 |
| 16GiB | 约56秒READY，同样全部正确 |
| 24GiB | 600秒仍无READY，停止该档 |

24GiB卡住时CPU用时保持44.65625秒，物理可用约32GiB、commit可用约25GiB。因此“空闲RAM很多”并不能证明继续注册就一定成功。它支持注册／映射资源条件的解释，没有定位Windows或HIP内部的具体限制机制。

最终1M采用16GiB。它是本模型、这台机器、这套引擎／运行库下通过的配置，不是所有128GB机器统一的上限。256K仍能使用已验证的32GiB方案。

文件：`shared-kv.patch`、`layer-shared-kv.cpp`、`session-shared-kv.cpp`、`generate-shared-kv.cpp`、`build_shared_kv.py`、`shared-kv-ladder.summary.json`。

## 7. Prefill为什么比老单卡慢，后来怎么恢复

### 7.1 先把对照条件补齐

“1M上限”和“这次输入1M”是两件事。本次都输入64K，仅改变容量设置时，模型仍可能预留不同大小的索引／KV工作区。

同引擎、pin16、模型、profile来源、MTP、视觉和64K输入，只改max-context：256K上限约3311–3371，1M上限约2154–2176，低约35%。每张GPU的专家缓存约减少1.9GiB，auto chunk从32768降到29440。

之后直接复测主槽老单卡1M：2955–2984，确认了用户说的约3000。相同fork单卡pin16：2657–2671，也高于原双卡1M的约2160。不能用“额外卡更慢”或MTP／DF2不同直接结束分析。

老单卡与fork还存在默认参数、注册额度和近似路由差异，不能把它们的全部差距都算作编译版本损失。

### 7.2 分块数量发生了跳变

原DP要求平衡的偶数块：

```text
k = ceil(输入长度 / 可用chunk上限)
k至少为2；若为奇数，再补成偶数
每块长度按256对齐
```

以64K为例：

| 可用chunk上限 | 分块 |
|---|---|
| 32768 | 2 × 32768 |
| 29440 | ceil(65536/29440)=3，补为4 → 4 × 16384 |

分块上限只降低约10%，块数却翻倍。专家流入、跨卡状态发布以及GEMM批次大小都受到影响。模型的首尾少量模板／checkpoint片段不改变这个阈值结论。

这解释了为什么不能按总显存、两卡单独吞吐的平均值，或者chunk上限的比例简单推算性能。

### 7.3 保留TP，调整reserve和借槽比例

Prefill会借用专家缓存的一部分作为工作区。reserve越大，能分给专家的缓存越少；借出越多，Prefill缓冲越宽，但临时驻留的专家也更少。二者需要同时检查实际日志。

| 双卡1M配置 | 首个64K Prefill | 图片后64K Prefill | 128K Prefill / Decode | 外卡全加载后余量 |
|---|---:|---:|---:|---:|
| reserve2560 / lend93 | 2164.2 | 2174.7 | 2722.0 / 74.1 | 约1556MiB |
| reserve1536 / lend93 | 3192.9 | 3231.1 | 3480.5 / 86.2 | 532MiB |
| reserve2048 / lend97 | 3141.0 | 3206.0 | 3449.5 / 87.6 | 1042MiB |

后两组恢复32768 chunk，TP Decode和原DP都保留，全部正确通过图片、中文、两次64K及128K检索。最终采用2048／97，给外卡多约510MiB余量，Prefill只有小幅差异。

最后将此参数写到真实BAT引用的live配置再次启动，得到3145.9、3191.5及128K的3449.6 / 85.2，全部正确。原约2160的1M配置提升约46–48%，64K也略快于本轮老主槽单卡。

降低reserve同时增加缓存并跨过分块阈值，无法仅凭这一组实验把全部收益精确分摊到某一项。

移除Decode TP的对照虽然计时更快，却只回答了web_search工具调用，没有暗号，输出长度也错误；该配置未采用，失败速度不计作有效性能。

文件：`check_vision_matched_context.py`、`compare_1m_resource_paths.py`、`check_1m_chunk_headroom.py`、`check_1m_balanced_headroom.py`及同前缀JSON／日志。

### 7.4 还做过哪些常规调优

- 每卡stager线程4→2有小幅收益，采用2；增加到8没有确认收益。
- MMQ tile row cap64→128／0没有足够收益，保留64。
- spec4/min-p0.70→spec6/min-p0.5没有确认收益，保留原值。
- 若诊断显示复制等待、QSA选择或GPU GEMM占时大，不要只因CPU有空闲就增加CPU workers。
- stage统计中CPU staging、复制、GPU计算可能重叠，不能把它们相加当作总耗时。
- 8K、16K可能走TP Prefill，64K及更长走DP；不同路径的数据不能混作一个优化收益。

网上分支参考IQ4曾有约两倍Prefill，但平台为Linux、9950X3D2、128GB DDR5、双PCIe4×8。它与本机CPU、RAM、驱动环境、链路、视觉、容量等条件不同，不能把参考数字当成本机必达指标。

## 8. 正确性如何验，哪些问题仍未解决

### 8.1 先短题，再长题，再重复启动

本次验证顺序：英文READY → 中文首都 → 算术 → 长输入暗号检索 → 长中文／多轮 → 图片 → 图片后长输入 → 新进程重复。

长输入采用项目 `rdna3/bench.py` 的精确prompt和tokenizer；三处暗号分布在不同位置。检查输入计数、输出长度、内容，以及timings里的cache_n。固定temperature0、seed42、关闭thinking，每个独立实验复制相同来源的expert profile。

重复回答的Decode会随专家缓存学习、MTP接受率、生成内容变化。首轮与后几轮差别较大，不能拿最快一轮承诺日常速度。新服务进程的冷启动，也不等于Windows重启或断电。

### 8.2 容量边界需要理解服务行为

256K测试输入261888、请求256输出，实际正确输出248。源码预留 `CTX_SLACK=8`：

```text
允许输出 = min(请求输出, max_context - 实际输入 - 8)
262144 - 261888 - 8 = 248
```

初版测试器把它误判失败。保留原始记录，另写review只修正已核对源码的计数预期，没有删除数据或放宽暗号正确性。

容量应包含模板、历史、图片tokens和输出预留；对新模型应核对它所在引擎的规则，不能假定同样保留8。

### 8.3 仍开放的问题

1. 原DP配置曾有一次独立冷启动长输入错答，后续原参数及关闭early TP各三次都正确。不能把关闭early TP说成已修复；该改动没有采纳。
2. 单卡外接的一次预热卡住未充分定位；单卡异步提交候选因错答没有采用。
3. 移除TP等实验还发生过无关代码／工具调用／NaN，失败记录保留。最终配置部分请求通过不代表所有路径已正确。
4. 完整400K、700K、1M输入以及长时间真实会话尚未由本轮自动测试覆盖。
5. 用户遇到过屏幕黑块闪烁，移动鼠标后消失。没有建立它与显存占满或模型错答之间的因果关系；不能写成已定位的同一错误。

遇到错答时记录：时间、正在用的BAT／配置、引擎SHA、原始输入／响应、prompt/cache/输出计数、上一轮是否图片／长上下文、engine日志和系统事件。速度再快，也应先将该请求标为失败。

## 9. 换Maya／Strata其他模型时怎么复用

### 9.1 可以迁移方法，不能照搬Qwen参数

对于计划中的Maya / GLM5.3 Flash和Strata / DS v4.1 Flash，先取得实际项目链接／版本、模型元数据、量化格式与运行日志，再确认支持的后端和并行方式。本文没有验证它们已支持当前分支。

| 本次配置／经验 | 新模型应如何处理 |
|---|---|
| 设备bus、带宽、系统日志核对 | 可以复用方法；换槽后重做映射 |
| 固定prompt、无缓存、独立profile、公平对照 | 可以复用方法；使用新模型tokenizer |
| pin16、reserve2048、lend97 | 只作参考；根据新模型KV／专家／工作区重新测 |
| 分块阈值检查 | 复用思想；先确认新引擎算法和实际chunk |
| `draft_vocab_zh60k.bin` | Qwen相关token编号；不能给GLM／DS直接用 |
| Qwen MTP／DF2包 | 必须匹配新模型及引擎支持，不能混用 |
| Qwen expert profile | 建立新的独立profile；专家数量／层结构可能不同 |
| Qwen mmproj | 视觉须用匹配模型的投影文件，并确认模型／引擎支持 |
| `layer_split="24"`、head／KV布局 | 按新模型层数与结构重新决定 |
| 本次packed／提交／共享KV补丁 | 只对读过并验证的代码路径有效；环境变量在别的build可能不起作用 |
| Qwen YaRN scale4、1M上限 | 按新模型位置编码和官方／引擎支持核对，不能凭改数字获得可靠长上下文 |

用户此前DF2／MTP对照速度接近，DF2可节省显存；本次未继续开发DF2。旧BAT文字可能与实际JSON不同，判断草稿器要看配置与加载日志。

### 9.2 建立模型独立基线

建议逐步做以下矩阵，每轮记录实际运行参数，正确通过再加负载：

1. 主槽单卡，原引擎默认推荐配置，短题＋4K／16K。
2. 主槽单卡，同一64K输入，固定较小容量，再扩大容量比较。
3. 外接单卡，保持其余条件，测64K和完整回读。
4. 双卡默认方案，对比同引擎、同精度、同草稿器、同容量的主槽单卡。
5. 双卡逐项调整分块、缓存／reserve、注册额度、搬运线程；一次只改一项，需要跨阈值时明确记录组合改变。
6. 图片／多轮／长输出交错，以及独立进程冷启动。
7. 128K通过后逐步扩大到256K、400K、700K，最后接近模型实际支持的上限。记录质量，避免只看速度。

如果新模型没有稀疏专家、没有MTP或使用不同注意力结构，本次专家cache／MTP／QSA优化不一定适用。先从该引擎的推荐基线开始，不把Qwen特有的几十个开关一起塞进去。

本次GPU无P2P，外卡带宽比主槽低。新引擎若要求高频大规模TP交换，收益可能不同；必须看复制等待和单卡对照。双卡能同时计算，不等于任意模型／拆分方式都能接近两倍。

### 9.3 建议保存的实验表

```text
实验ID / 日期 / OS与驱动 / 引擎版本与SHA / 模型与量化
物理GPU与bus / 负载下链路 / 实际显存和RAM占用
原始参数 / 改了什么 / 为什么改
容量上限 / 实际输入token / 输出token / cache_n
实际chunk / 块数 / 专家cache与借槽 / 复制等待
Prefill / Decode / MTP接受率 / 首轮与后轮
正确性通过或失败 / 原始请求响应 / 日志 / 是否采纳
```

短筛选用于排除明显无收益的参数；最终候选至少同协议重复并检查新进程，报告中位数及范围。正确性失败请求的时间可以保留用于定位，不能计入成功吞吐。

## 10. 本机已有脚本怎么用

以下命令是供以后手动研究的示例，写入本文时没有运行。运行GPU探针／benchmark前先停自己的模型服务；不要一边用模型一边烤机或跑这些探针，也不要按程序名批量终止别人的进程。

```powershell
Set-Location D:\codex-work\strata-win-20261107
```

### 仅读取配置／检查服务

```powershell
Get-Content .\dual7900-mtp-vision-1m-test.json -Raw
Invoke-RestMethod http://127.0.0.1:8080/health
```

`/health` 能看到上限、loaded和images。查看engine日志里实际GPU、runtime路径、草稿器、auto chunk，不只看BAT标题。

### 最小二维上传复现

该脚本专用于本次Windows HIP DLL和配置结构；换成其他后端应使用对应探针。

```powershell
python -X utf8 hip_copy_diagnostic.py --runtime engine-service --base dual7900-mtp-vision-1m-test.json --output study-hip-copy.json --source-file study-hip-source.bin --skip-bandwidth
```

### 精确64K性能／内容对照

先确认 `bench-prompts` 对应长度／r0-r2已存在。使用独立tag，不覆盖已有实验。

```powershell
python -X utf8 run_windows_bench.py study-1m-64k-a --base dual7900-mtp-vision-1m-test.json --profile-source D:\strata-qwen224\era-route0-profile.bin --lengths 65536 --output 256 --repeats 3
```

该脚本使用18107端口，复制独立profile，保存配置、逐请求JSON、summary、日志，并清理自己启动的服务PID树。它仍需要模型GPU资源，不能与桌面服务同时测速。

`generate_exact_prompts.py` 读取本目录的 `baseline.json`，通过项目 `rdna3/bench.py` 使用本次Qwen的tokenizer与请求模板，生成4096、8192、65536、131072输入长度各r0–r2三份prompt，并校验模板转换后的token数。该脚本没有命令行参数解析或 `--help` 接口；直接运行会生成文件，不应把 `--help` 当作只读查看。新模型必须先适配自己的配置、tokenizer与请求模板，不能直接沿用Qwen的token计数或盲目运行此脚本。

### 视觉／容量功能检查

```powershell
python -X utf8 check_dual_vision_launch.py --label 1M --config dual7900-mtp-vision-1m-test.json --extra-length 131072
```

该脚本会启动8080服务、测两次64K、图片、中文及额外128K，并停止自己启动的服务。它会更新此配置前缀的测试日志／结果；研究时建议先复制配置，改log/profile路径并使用新文件名。

### 系统事件与内存观察

```powershell
Get-Process strata -ErrorAction SilentlyContinue |
    Select-Object Id,CPU,PrivateMemorySize64,WorkingSet64

Get-CimInstance Win32_OperatingSystem |
    Select-Object FreePhysicalMemory,FreeVirtualMemory,TotalVirtualMemorySize

Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger'} -MaxEvents 10
Get-WinEvent -FilterHashtable @{LogName='System';Id=4101} -MaxEvents 10
```

CPU累计用时长期不增长只是“没有前进”的线索。private bytes、工作集、commit和物理RAM含义不同；一次看到有空闲，不能排除GPU映射额度或等待问题。事件要对齐实验时间、查根口及子设备。

## 11. 构建与回退怎么留证据

本次没有重置原工程的其他修改。修复源码和新对象放独立目录，使用原Ninja编译命令的参数，只替换相关对象链接到新exe，并复制已核对的运行库到exe旁。保存源码diff、编译／链接命令、日志及SHA256。

原工程：`D:\anan-work\Strata-rdna3-fixed`。实验／最终文件：`D:\codex-work\strata-win-20261107`。模型：`E:\Strata-0.1.13\Strata-data`。

| 产物 | SHA256 |
|---|---|
| 最终256K `engine-service\strata.exe` | `8f66abfe8d3c92693f8cdd73e4823d0d0a7fb03cbcbe4aa4f74deb6296268a52` |
| 最终1M `engine-shared-kv\strata.exe` | `f916b44e3bd65d568720a444a6103a527d304a5bbbc11f64818d61c3759732cc` |

补丁只有编译进exe，相关开关才可能生效。在别的Maya／Strata发行版设置同名变量，不能假定代码自动获得修复。迁移代码应确认分支／ABI／布局和适用条件；换引擎或运行库后重做最小复现与正确性检查。

桌面安装脚本检查live配置SHA和测试时的引擎SHA一致再复制BAT，保证测试与启动指向同一产物。旧BAT、原profile未覆盖。

归档：

- `archive-1m-original-pin12-reserve4096`：原1M初始化失败版本。
- `archive-1m-shared-pin16-reserve2560`：能正确运行但约2160的1M版本及请求。
- 独立实验前缀仍保留成功／失败结果，含未采用的单卡提交和no-TP方案。

研究回退时复制已验证配置和匹配exe，不把某个失败版本的开关混进最后配置。当前桌面1M已使用通过的pin16／reserve2048／lend97，可以在其副本上实验。

## 12. 资料索引与结论边界

| 资料 | 主要内容 |
|---|---|
| `AB-STRATA-WINDOWS-TP-20261107.md` | 乱码权重定位、提交修复、早期Gen3下的隔离与失败记录 |
| `AB-STRATA-WINDOWS-M2-BEFORE-20261107.md` | 更换转接路径前的外卡单卡基线 |
| `AB-STRATA-WINDOWS-M2-AFTER-20261107.md` | Gen4外卡单卡、首次偶发卡住和未采用候选 |
| `AB-STRATA-WINDOWS-GEN4-DUAL-20261107.md` | 双卡Gen4、缓存调优、1M共享KV、逐档注册、分块恢复与最终交付 |
| `dual-vision-launchers-manifest.json` | 两个桌面BAT实际配置、exe、端口和验证依据 |
| `shared-kv-build-manifest.json` | 新引擎及对象文件SHA |

前几份报告有阶段性“仍在测试”的表述；当前最终配置与开放问题以最新Gen4双卡报告和本笔记为准。详细报告同名副本已在Windows桌面。

本次确认并处理了错误上传、双卡提交等待环的可用绕行、重复固定页申请，以及1M分块阈值导致的性能损失。硬件接法也确实影响带宽。它们是不同层面的证据；不能归成一个“Windows底层全有问题”或“OCuLink一定坏”。

可复用的研究流程是：**先核对实际运行对象，取得原始数据，找首次分歧；构造单变量／最小复现；正确性通过后才测速；保留失败和回退产物；把仍未定位的部分写清楚。**
