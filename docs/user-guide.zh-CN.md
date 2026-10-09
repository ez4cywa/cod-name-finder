# COD Name Finder 一键使用教程

适用版本 **2.3.0**，Windows 11 x64。软件从已导出的哈希文件夹或离线资产快照读取目标，生成候选并计算名称；正式结果必须完整键命中、独立回算通过，再排除所选 Saluki 索引的已有键或原样名称。未知模型不在目标范围，已命名模型可以提供线索。

界面采用 Avalonia 液态玻璃风格与 .NET NativeAOT。文件处理继续使用安装包自带的 Python 后端，计算支持 Rust CPU 和可选 OpenCL GPU。新电脑使用文件夹或完整离线快照计算时，无需安装 Python、.NET、Rust、Git、Ghidra、游戏或 Cordycep。只有捕获新快照的电脑需要用户自己的兼容 Cordycep 和游戏文件。默认离线、本地输出，没有公开发布或自动提交步骤。

本版源码回归通过741项Python测试。安装包的SHA256和最终EXE／NativeAOT逐项验证清单随[2.3.0发行附件](https://github.com/ez4cywa/cod-name-finder/releases/tag/v2.3.0)提供；下载后保留完整安装负载及同版本教程。

## 第一时间应该如何使用

1. 退出旧版，运行 `CODNameFinder-2.3.0-Setup.exe`，从开始菜单或桌面启动。
2. 点击“使用教程 · F1”或按 **F1**。教程随软件提供，离线可读。
3. 在旧电脑或 Saluki 目录复制实际的 `hash_pkg`，放到新电脑的数据目录。新电脑不必运行 Saluki，但正式查找必须有可读取的 CDB 名称索引。
4. 先按下一节跑通占位动画示例，再选择自己的输入：已有导出文件选“已导出的哈希文件夹”；拿到完整捕获目录选“离线资产快照 · JSON / IDS”，选择其中 `snapshot.json`。使用原项目现代 `.ids` 时，把同名 `.pools.txt` 一起复制。首次建议 CPU、完整键、关键词留空、社区选项保持关闭。
5. 选择作品、名称域、规则和资产类型，设置独立输出目录，点击“估算候选与耗时”。看清未知目标、规模与时间区间后，点击“确认计算并导出”。
6. 结束后用“打开新增 CSV”查看 `new_names.csv`。向 Saluki 安装时先备份旧索引，再复制本次的合并文件。

例如本机可以把 `D:\_tiqu\Saluki\hash_pkg` 复制到 `D:\NameFinderData\Indexes`；将输出设置为 `D:\NameFinderData\Results`。程序不会修改原游戏媒体或原 Saluki 索引，安装名称的复制操作由你完成。

已有 Cordycep 数据时，先按下文“读取已经加载的 Cordycep”保存快照，然后再估算和计算。捕获只收集目标键和候选字符串，不会立即把全部哈希变成名称。把整个捕获目录与自己的 Saluki 索引复制到新电脑后，就可以继续离线计算，不需要在新电脑启动加载器。

### 本机 BAT 启动的最短流程

本机已有 Cordycep 和游戏文件时，可直接在软件选择启动脚本：

1. 选择 **COD2026** 和独立输出目录，展开 **“Cordycep 捕获 · BO7 / COD2026”**，选择 `D:\_tiqu\Cordycep`。
2. 在 BAT 下拉选择 **`RunMW7Beta.bat`**。看不到新文件时点击 **“刷新 BAT”**；也可选择目录根中自己的其它 BAT。
3. 点击 **“运行所选 BAT 并捕获”**并等待完成。如果 Cordycep 已经运行，等待它加载稳定后改用 **“读取已加载实例”**。
4. 成功后界面自动选中生成的 `snapshot.json`。选择实际 Saluki 索引及本次资产类型，例如 `xanim`，再按 **“估算候选与耗时 → 确认计算并导出”**。

BO7对应的默认文件是 `RunBO7.bat`，但本次新构建的 BO7 启动尚未通过现场验证；先手动运行并确认加载成功，再尝试读取。详细范围、失败处理和命令行例子见后文。

不要只复制 `CODNameFinder.exe`：保留整个安装目录中的 `engine`、教程、资源和示例。偏好保存在 `%LOCALAPPDATA%\CODNameFinder\settings.json`。从1.x旧界面升级时需重新选择目录；2.0.x的兼容偏好可以继续使用。窗口较小时滚动输入区域，下方计算、停止与结果操作仍可见。

## 用附带示例跑通一次

示例哈希动画是占位文件，不是游戏媒体；示例索引只能用于验证操作流程。

| 界面字段 | 第一次选择 |
|---|---|
| 输入来源 | 已导出的哈希文件夹 |
| 哈希文件夹 | 安装目录 `examples/one-click/hashed-assets` |
| 作品 | COD2026 |
| 名称域 | 资产名称 / 动画包 / 声音库 / 声音文件 |
| 哈希规则 | `iw-resource63` |
| 资产类型 | 动画 · `xanim` |
| 已有名称索引 | 安装目录 `examples/one-click/existing-indexes` |
| 补充名称词典 | 留空 |
| 关联名称推测 | 保留默认勾选 |
| 其他已命名资产 | 留空 |
| 输出目录 | 安装目录外，例如 `D:\NameFinderData\ExampleResults` |
| 结果关键词 | 留空 |
| 运算方式 | CPU · Rust 内核 |
| 文件名仅保留低60位 | 不勾选 |
| 更多选项 | 保持默认，社区同步关闭 |

点击“估算候选与耗时”，再点击“确认计算并导出”。首次预期验证3项、排除已有1项、输出2项：`rex_mp_strafe_walk_1` 和 `rex_vm_misc_laser_pointer_fire`。再次用完全相同配置运行时，已扫区间可以复用，仍应恢复相同的已验证结果供导出；新扫描数量可以为0。

完整运行成功后会保存完整计划缓存。相同输入再次估算或运行，可跳过语料解码与候选规则重建；每条名称仍重新回算，Saluki已有条目仍重新排除。日志会显示“完整运行复用”。保留输出根目录的 `.namefinder-ledger.sqlite` 才能跨运行复用；删除它只是清空缓存，已有CSV/CDB结果不受影响。输入目录的目标、明文名称线索、词典、Saluki索引或算法实现发生变化会重新准备。停止或预算不足的运行只保存已完成批次，不能冒充完整计划缓存。

## 一键计算并导出

真实运行按“输入 → 估算 → 确认 → 保存结果”的顺序进行。

1. **目标与规则。** 选择输入来源及已导出的哈希文件夹或快照 `snapshot.json`，然后选择作品、名称域、哈希规则和资产类型。名称域决定这些键代表哪类名称；资产类型决定本次使用的目标类型。快照中的类型来自已核验池映射，不能用下拉框将未知池强行解释成声音或脚本。
2. **已有名称与线索。** 选择实际 Saluki CDB 索引。按需要添加补充词典；支持的目标类型可启用关联名称推测，并加入已经命名的其他资产目录。2.3.0 的声音新规则和按类型的动画／alias、武器／图片／材质规则沿用此开关，无需额外启动脚本。
3. **结果位置与范围。** 输出目录放在目标、索引及关联资产目录之外。第一次关键词留空，预算先用默认1000万候选、120分钟。默认排除材质，目标是材质时需取消该勾选。
4. **先估算。** 点击“估算候选与耗时”。如果显式开启社区表，界面会先只读同步或复用缓存，再做估算；普通离线任务直接估算。
5. **看估算再确认。** 日志显示全部候选空间、本次预算内工作量、已扫可复用范围、随机碰撞期望、CPU时间区间，以及每种类型的目标数 / Saluki已有键数 / 未知数。配置有变化时估算会失效。
6. **开始并保存。** 点击变为“确认计算并导出”的按钮。程序后台生成和匹配候选，命中仍独立回算。预算耗尽或“停止并保存”都会保存已完成批次与已验证结果。

候选总空间不是本次一定计算的数量。时间区间依据本机CPU小样本外推，GPU速度未由这个区间保证；索引读写、设备初始化、目标缩小、命中数量都会改变实际耗时。碰撞期望是“本次候选量 × 未知目标数 / 2^有效位数”的统计提示，不是单条结果错误的概率；名称仍需要完整键与证据核验。

按类型差集只说明“目标完整键是否已在当前Saluki索引”，不能把未知数当作一定可以找到的数量。关键词按名称原文在命中后筛选，不提前删掉供体语料。例如填 `mike4` 只输出相关命中；第一次留空可避免隐藏结果。

## 读取已经加载的 Cordycep

适合已有加载器、已经加载 fast file 的电脑。当前登记 **COD2026 Beta / MW7 内部代号**和 **BO7 正式配置**的捕获适配，并严格核对本地加载器、模块和配置的 SHA256。两个本地 CLI 构建的文件版本均为 **2.9.0.0**：旧构建 SHA256 为 `fe43506a599fd84472c81599ace976b6ee6cde8b545745ea7ff0e3046fe1e1e7`，当前首选构建为 `a3a700bd4080f1d3eb7ee7084e0f42abc597c33f5a6eeded154105239f43b6f9`。每个构建独立绑定作品配置、游戏模块和读取布局；版本号相同不代表任意 CLI 都能使用，未知构建不会放宽校验。原来生成的完整离线快照仍可使用。

**2026-10-05 当前新 CLI 已通过 `RunMW7Beta.bat` 的真实启动、独立只读检查与完整捕获验证**：本机本轮约10.84秒，保存337,958条原始键记录和43,105条候选字符串，状态/CSI一致，512个40字节池记录、96字节节点前缀以及414项类型表与内存检查一致，16个已适配池映射符合。脚本本轮加载的是 common 集合；这些数量是捕获记录和候选文本，不是已经找到的名称，不代表整款游戏已加载。不同加载集合或机器的数量与耗时会变化。

**BO7同日实际运行新 CLI 的 `RunBO7.bat`，约6.85秒后未返回可核对的完成提示，仍未通过现场捕获验证；原因未确认。** BO7可先手动运行自己的脚本，确认加载器正确加载，再选择“读取已加载实例”验证。没有完成提示不能直接证明具体授权、配置或游戏版本原因。

1. 在 Cordycep 中完成自己需要的 fast file 加载，等待加载结束。不要在捕获期间切换 handler、卸载或继续加载文件。
2. 在 Name Finder 选择对应作品。捕获阶段不用先选好最终动画/声音类型；捕获完仍可按类型分批计算。
3. 设置独立输出目录，例如 `D:\NameFinderData\Results`，展开 **“Cordycep 捕获 · BO7 / COD2026”**，选择 Cordycep 安装目录，例如 `D:\_tiqu\Cordycep`。
4. 点击 **“读取已加载实例”**。软件只读匹配的加载器实例，核对状态文件的 PID、游戏标识、模块和配置版本，遍历已适配池并检查重复读取的一致性。它不会向用户已有实例发送加载、卸载或退出命令。
5. 成功时，完整捕获目录保存在 `结果目录\captures\capture-日期-随机后缀`。界面自动选择 **“离线资产快照 · JSON / IDS”**和新生成的 `snapshot.json`。
6. 再选择本轮要找的资产类型与名称域。第一次建议动画 `xanim`、资产域 `asset`、`iw-resource63`、CPU，保持完整键。选择实际 Saluki 索引，点击“估算候选与耗时”，确认后计算。

捕获完可以继续使用原 Cordycep，也可以由你自行退出；后续计算只读快照。存在多个相同目录实例、状态属于另一个 PID 或作品不匹配时，软件拒绝猜测。GUI不明确区分的多实例可用命令行 `--pid` 指定实际实例。

### 如何理解“捕获完成”

现代适配器核对 **512 个池、40 字节池记录、96 字节节点前缀**，这些只是已核验的读取格式，不会执行游戏模块里的函数。当前正式名称计算范围为以下 **16 个池、15 种软件类型**，全部采用 `iw-resource63 / asset`：

| pool | 软件类型 |
|---|---|
| 6 | xanim |
| 10 | material |
| 14 | image |
| 26 / 27 | soundbank / soundbanktransient |
| 55 | localize |
| 56 / 57 | attachment / weapon |
| 63 | rawfile |
| 64 / 65 | scriptfile：gscobj / gscgdb 文件资产 |
| 66 | stringtable |
| 87 | animpkg |
| 110 | scriptbundle |
| 116 | keyvaluepairs |
| 186 | sndasset |

模型与模型表面池 7、8 排除。未知池保留数字池号和原始键用于诊断，不进入名称计算。软件的21种文件夹类型继续可用，但此通用捕获器没有把银行内部 alias、骨骼字符串、脚本符号、Dvar 或 Omnvar 符号自动拆成目标；名称相似的资源对象不等于这些特殊哈希域。

`complete=true` 表示 **当前已加载集合中的全部已适配非模型池读取稳定**，不表示整款游戏全部文件已加载。`whole_snapshot_stable` 单独记录所有诊断池的状态；未知池变动时它可以为false，而已适配范围仍为complete。每轮报告明确保存范围、逐池稳定性和读取错误。未知池的不稳定数据始终不参加正式计算。

捕获数量和字符串数量不是“已经找到名称”的数量。`strings.txt` 中的字符串会自动作为候选线索，仍需按本轮规则命中完整目标并通过独立回算。关键词只筛选已验证名称，不把相似字符串直接当作答案。

点击“停止并保存”或遇到已适配池读取失败后，已进入池读取阶段的捕获会保存 partial 排查资料；它不能作为完整快照计算。尚在启动或初始化阶段停止时，没有可保存的资产快照。保持加载器稳定后重新捕获，不能像候选计算账本那样从中途接着读取旧内存地址。

## 在软件中启动新 Cordycep 实例

需要用户本机已经安装兼容加载器、对应游戏文件与所需依赖，且所选目录没有正在运行的 Cordycep CLI。即使现有 CLI 还在初始化、尚未生成状态文件，软件也拒绝在同目录重复启动。已有实例先等待加载稳定，再用上一节的读取按钮；软件不会替你关闭它。

COD2026的新 CLI 已在本机通过 `RunMW7Beta.bat` 启动并完整捕获当前 common 集合。BO7的新 CLI 在本次真实 `RunBO7.bat` 验证中未返回可核对的完成提示；软件会报告启动失败，用户也可先手动运行 BAT，确认加载后再读取。失败原因尚未确认，不影响已有完整快照的离线计算。

1. 选择作品、Cordycep 目录和独立输出目录，展开 **“Cordycep 捕获 · BO7 / COD2026”**。
2. 在 **“启动脚本 · 目录根 BAT”**下拉选择本次要运行的脚本。这里只列出所选目录根的 `.bat`，支持中文、空格和大写扩展名；子目录脚本和 `.cmd` 不在列表中。
3. COD2026优先选择 `RunMW7Beta.bat`，BO7优先选择 `RunBO7.bat`；没有默认文件时选列表中的第一个。手动选择其它 BAT 后，点击 **“刷新 BAT”**仍保留该文件；切换目录或作品时重新按作品选择。所选目录和脚本保存在偏好中，捕获、估算或计算期间不能修改。
4. 点击 **“运行所选 BAT 并捕获”**。软件通过 Windows `cmd` 真正运行该 BAT，以脚本所在的 Cordycep 目录为工作目录；BAT中的相对路径、环境变量和批处理步骤按 Windows 处理，不再只解析固定单行加载器命令。加载集合由脚本决定，软件不隐式追加 `loadall`。
5. 等待加载、捕获结束，再检查范围报告与自动选中的 `snapshot.json`。软件以 Windows Job 管理本次启动的批处理及加载器进程，结束或停止时只清理本次拥有的进程。用户原有实例保持只读。

先确认所选 BAT 能在本机正确启动对应作品，脚本里的游戏目录必须存在。加载成功只证明加载器当前集合可读；common 文件、命令提示符和条目数量都不能证明完整游戏已加载。CLI可显式请求 `--load-all`，但更多文件可能不兼容、缺失或加载耗时很长，不能保证全游戏成功。需要更大集合时，也可按自己的脚本或独立 Cordycep 加载所需数据，等待稳定后再读取。

下拉选择不会修改 BAT。脚本启动了不同作品、配置/转储与登记 build 不同、启动进程退出或加载超时，捕获会报告失败；核对脚本后重试，或自行启动并用读取按钮验证。读取权限不足时应使工具与所选加载器的本地权限相匹配。工具不捆绑或修改用户的加载器、游戏模块和授权文件。

## 把完整快照带到新电脑计算

在有游戏的电脑捕获一次，复制 **整个 `capture-*` 目录**到新电脑，例如 `D:\NameFinderData\Snapshots\MW7-common`。同时复制自己的实际 Saluki `hash_pkg`。只复制 `snapshot.json` 会丢失它引用的数据，不能计算。

| 捕获文件 | 用途 |
|---|---|
| `snapshot.json` | 首选输入，记录作品、build、范围、池映射、稳定性及各文件SHA256 |
| `records.csv` | 16位原始uint64键、软件类型和池号；已验证类型与未知诊断均保留 |
| `strings.txt` | 候选文本；不代表已验证名称 |
| `pools-report.csv` | 逐池类型、计数、规则、稳定性与错误 |
| `snapshot.ids` / `snapshot.pools.txt` | 供旧工具交换的63位副本及清单；现代计算优先使用增强JSON |

新电脑上选“离线资产快照 · JSON / IDS”，选择复制目录中的 `snapshot.json`，再选择与快照相同的作品、`asset / iw-resource63`及本轮资产类型。可以选“自动识别全部非模型资产”处理同规则的已适配类型，或先动画后声音分批运行。材质开关仍生效。补充词典和关联名称可留空，快照自带字符串自动导入；社区默认关闭。

接下来流程与文件夹相同：索引 → 估算候选、碰撞与按类型Saluki差集 → 确认计算 → 新CSV和增量CDB → 检查合并目录。完全相同快照及来源的再次运行可以复用账本；0次新扫描仍可重新回算并恢复原命中供导出。快照内容、目标范围、词典或索引变化会影响内容指纹，旧缓存不会被当成新目标的证明。

增强格式保留 **raw64** 原始键，按池的已证名称域做比较。原项目 `CODIDS v1 / .ids` 已统一清掉最高位，只能提供63位证据；软件不会把这些键提升为full64来认证现代alias或骨骼。BO4/BOCW旧快照按已经独立登记的该作数字池映射识别，池文字标签用于核对。

### 使用原项目的现代 `.ids`

2.3.0 增加 MWII、MWIII、BO6、BO7 和 COD2026 五部作品的 `CODIDS v1` 导入。这是离线输入兼容，不会为本地 Cordycep 自动增加这些作品的现场捕获适配。

1. 复制整对文件，例如 `modwar7.ids` 和 `modwar7.pools.txt`，保持在同一目录及相同文件名前缀。
2. 在软件选“离线资产快照 · JSON / IDS”，选择 `.ids`，再选择其实际作品。公开快照中的 `MODWAR22 / YAMYAMOK / BLACKOP6 / BLACKOP7 / MODWAR7` 分别对应 MWII / MWIII / BO6 / BO7 / COD2026。
3. 首次选择 `asset / iw-resource63 / xanim` 及实际 Saluki 索引，按普通估算、确认、导出流程计算。可改选同资源域的其他受支持非模型类型。

现代池号只标识该份捕获清单的位置，可能经过合并或追加。程序按同名 `.pools.txt` 的资产类型名映射，并核对作品和计数；不能把这些数字池号套入上文的本地实时40字节池布局。缺少池清单会明确报错，未知类型保留原始记录并排除正式计算，模型仍排除。

清单中的 `sound_alias` 只有63位，而现代 alias 的规则是满64位。该快照的 alias 池不能被选作满64位正式目标，也不能凭“低63位一致”直接导出。可信 alias 名称可以作为声音文件推测线索；只有另有完整键且通过独立回算的当前 alias，才能成为正式 alias 结果。需要该域结果时使用保留原始64位键的受支持输入。

增强快照中的类型、掩码、完整性或SHA不能手工修改。读入器会核对作品、build、排序、数量、池映射和文件内容，坏文件、缺附件、错误作品、未知pool强贴标签或partial都会被拒绝。现代 `.ids` 的加载集合及版本证据比增强JSON少，不代表全游戏完整。

## 哈希文件夹与21种资产类型

程序递归读取导出文件名清单，不解析媒体内容中的引用哈希。64位规则通常识别8至16位十六进制键；32位规则也接受省略前导零的短键。建议保留完整16位键，不要从“少于16位”推断低60位截断。

| 文件名前缀或类型 | 下拉框类型 |
|---|---|
| `sound_`、`xsound_`、`sndasset_` | 声音资产 · `sndasset` |
| `anim_`、`xanim_` | 动画 · `xanim` |
| `image_`、`ximage_` | 图片 · `image` |
| `material_`、`xmaterial_` | 材质 · `material` |
| `sndbank_`、`soundbank_` | 声音库 · `soundbank` |
| `sndbanktransient_`、`soundbanktransient_` | 临时声音库 · `soundbanktransient` |
| `animpkg_` | 动画包 · `animpkg` |
| `rawfile_` | 原始文件 · `rawfile` |
| `scriptfile_` | 脚本文件 · `scriptfile` |
| `scriptbundle_` | 脚本包 · `scriptbundle` |
| `stringtable_` | 字符串表 · `stringtable` |
| `localize_` | 本地化 · `localize` |
| `weapon_` | 武器配置 · `weapon` |
| `attachment_` | 附件配置 · `attachment` |
| `structuredtable_` | 结构表 · `structuredtable` |
| `keyvaluepairs_` | 键值对 · `keyvaluepairs` |
| `soundbankalias_` | 声音银行别名 · `soundbankalias` |
| `bone_` | 骨骼名称 · `bone` |
| `scriptfield_` | 脚本符号 · `scriptfield` |
| `dvar_` | Dvar名称 · `dvar` |
| `omnvar_` | Omnvar名称 · `omnvar` |

`model_` / `xmodel_` 始终排除目标。`hash_` / `asset_` / `file_` 和裸哈希按明确扩展名、目录或所选类型判断。明确文件名前缀优先于下拉选择，不能把 `anim_` 文件强行解释为 dvar 样本。

“自动识别全部非模型资产”适用于同一名称域、同一算法的混合文件夹。不同算法或声音资源 / alias / SAB 混在一起时应拆开运行。JSON、CSV、CAST扩展名通常不能单独确定类型：`sndbank_<hex>.json` / `.csv` 属声音库，其内容引用的snd或alias不会被自动当作目标键。

未识别或导入数量异常时看报告的 `files`、`recognized_files`、`hashed_files`、`unrecognized`、`types_filtered`、`models_excluded`、`detected_type_counts` 和 `unrecognized_examples`。扫描文件数不等于待破解的唯一键数。

## 作品、名称域和算法怎么选

“作品、域与算法”一行提供三个下拉框。作品用于限制已证实域，名称域选择实际键的用途，算法仍可以手动核对。手动模式保留旧显式profile任务的兼容性，但不能因此声明某作品全部名称域已证实。

| 数据实际所属域 | 规则 |
|---|---|
| BO4 / BOCW 常见资源资产 | `fnv1a63` |
| MW2019 / Vanguard / MWII / MWIII / BO6 / BO7 常见IW资源 | `iw-resource63` |
| COD2026 rex资产、动画包、声音库、声音文件 | `iw-resource63` |
| MWII / MWIII 骨骼表 `fnv1a_bones` | `fnv1a32` |
| BO6 / BO7 骨骼表 `fnv1a_bones_v2` | `fnv1a64`，Treyarch满64位 |
| 现代声音银行别名 `aliases_v2`，含已验证rex alias | `fnv1a64`，Treyarch满64位 |
| BOCW骨骼 / notify字符串表 `fnv1a_strings` | `fnv1a60`，该表实际存储60位 |
| SAB旧版 / V17名称 | 对应 `sab-sdbm32` / `sab-fnv1a64`，按容器及样本核对 |

共20个profile、8个算法族，包含脚本、Dvar、Omnvar、安全字符串及声音路径规范化变体。声音库的资源名、bank alias 和SAB字符串是不同名称域；`scriptfile` 作为文件资产的名称也不同于脚本内部符号。BO4保留反斜杠的声音路径候选规则 `fnv1a63-no-fold` 需真实样本校准，不能把它推定到全部BO4声音。

本机 `D:\_tiqu\测试用\ainm\mw4_beta\animations` 的完整动画目标使用 COD2026资产域、`iw-resource63`、`xanim`，低60位选项不勾选。其他文件夹仍需核对自己的导出版本，不能仅凭“MW4”字样自动推断脚本算法。

## 未证实域如何手动验证

COD2026脚本符号、Dvar、Omnvar及未证实骨骼域没有默认算法承诺。常规用户应先使用已证实的资产域。

确有可信本地样本时，在“更多选项”勾选“手动启用未证实域”，明确选择对应名称域、算法和目标类型。把至少3对来自**本次目标目录、同一类型、不同完整键**的真实名称写入补充词典CSV/CDB/WNI。CSV为UTF-8、无表头两列：

```text
0123456789abcdef,真实名称一
1123456789abcdef,真实名称二
2123456789abcdef,真实名称三
```

上述数值只是格式示意，不能用来解锁。实际样本必须按所选规则独立回算一致，并且键确实存在于本次对应类型的完整目标中。低60位键、动画样本、跨作品借用词典或其他类型哈希不能解除脚本 / dvar / omnvar 门控。允许开关只允许验证，不会跳过校准和CPU复核，也不会将该规则变为所有COD2026版本的官方算法。

## 完整键、低60位初筛与实际60位表

只有确定导出器丢弃了高4位时才勾选“文件名仅保留低60位”。命中写入待核验区与 `pending-low60.csv`，不进入正式新增CSV或Saluki增量；存在高于低60位的有效值时会拒绝该选项。

`fnv1a60` 是另一件事：BOCW `fnv1a_strings` 的键本来就按60位存储。选择该已证实表/名称域时，以对应profile的完整存储键比较；不要额外勾选“文件名仅保留低60位”。这不表示任意60位文件都可以正式认证。

## 名称索引、补充词典与跨作品借用

已有名称索引可选Saluki安装目录、复制的 `hash_pkg` 或直接包含CDB的目录。读取PNDB/LZ4格式；缺失或损坏时会报错，不会跳过去重。真正要供Saluki使用的结果必须以你的实际索引作为排除与合并基础。

补充词典支持TXT、TSV、CSV、CDB、WNI。TXT每行一个完整名称；TSV取最后一列；CSV为无表头的“十六进制哈希,名称”。所有文本保存为UTF-8。普通名称仍只是候选；未知域解锁必须另满足真实完整目标样本要求。

“更多选项 → 跨作品候选”用于前作词典，字段名为 `borrowed_dictionary`。借用词汇只参与候选原名试算和作品前缀重新拼写，不进入本作校准、命名惯例统计或已验证排除集。前作名称原样试算无收益时，应增加本作真实模板；出现完整键命中后仍需正常回算才能成为结果。

保持音频完整内部路径和 `.lnn.85.48000.all` 等点尾，不要随意删除。Saluki导出把路径反斜杠变成下划线，不能唯一逆转；程序不将所有下划线替换为目录分隔符。

## 借助关联名称探索更多资产

“关联名称推测”一行的“根据已知名称推测关联资产”默认勾选。2.3.0 在原有动画、声音、声音库和临时声音库规则上，增加声音 alias 以及图片／材质的按类型推测；自动识别范围可以统一使用。没有适用规则的类型不会凭空生成名称。

已有Saluki索引中的已命名模型、图像、材质、武器与附件可提供身份词段。若还有本地已导出的明文命名资产，可选择“其他已命名资产”目录；只读递归文件名、文件stem及相对路径，不读取媒体内容，不把其中未知模型加入目标。

程序把身份词段放入实际观察到的动画或声音模板，尝试同一武器的其它名称；声音路径的相关重复标识和点尾按模板保留。一条模型名称不保证找到整套动画或声音，有限推测仍以完整哈希验证为准。

目标模板必须具有明确资产类型和相符 profile，并已命中当前同类型目标的完整键。TXT、文件名和没有原始键的其他线索先只作候选；若它们真实回算命中当前目标，才可学习该目标的命名惯例。外作名称不能因为看起来相似就被当作本作已经存在的文件。

2.3.0 增加以下有限规则，沿用同一开关：

| 规则 | 从哪里获得依据 | 会尝试什么 |
|---|---|---|
| 声音重复命名空间 | 当前已确认声音中的目录标识、文件名标识与编码尾；外作声音提供供体形状 | 同一标识在目录和文件名整词出现至少两次时，把相关出现同时替换；保留原始正／反斜杠 |
| alias 缺失声音文件族 | 当前 alias 及当前声音文件 | alias 文件族尚未在当前声音中出现时，找到至少3个下划线词段的最深公共前缀，借用该目标的完整目录及原 take＋编码尾 |
| 编码尾前末字节反求 | 已经通过原表键校验的声音拼写、当前目标实际编码尾及目标完整键 | 反求文件名主体的最后一个可打印ASCII字节，编码尾、斜杠及其他字节不任意枚举 |
| 动画到声音 alias | 已回算且型别明确的动画，以及当前 alias 模板 | 把有限动画身份／动作词段用于 alias 候选，仍用 alias 自己的满64位规则验证 |
| 武器词段到图片／材质 | 已核验动画／图片／材质／alias中的整词武器身份，以及当前图片／材质模板 | 保留武器类别与原模板命名空间，关联身份词段生成同类型名称，不把模型目标加入计算 |

例如当前声音有 `audio/wpn_plr_ar_alpha_fire_001.qnn.85.48000.all`，当前 alias 有 `wpn_plr_ar_alpha_reload`，会尝试 `audio/wpn_plr_ar_alpha_reload_001.qnn.85.48000.all`。目录、`001` 与完整点尾来自同一真实观察，不会组合成未观察到的编码／采样率。外作已经存在 `reload` 不会阻止本作探索缺失族。

原有关联生成保留最多800万组合、512个计划的上限。两条新声音计划合计最多100万候选、128条计划；两法都可用时，alias先跑，为namespace预留至多四分之一的计划与候选额度，默认最多留32条计划机会。只有一种方法时使用完整额度，namespace未用的额度可返回alias；只有1条计划等极小预算仍确定优先alias，不保证两法都跑。

末字节反求先按所选profile归一化并合并等价前缀，准备的字节运算与桶探测合计最多800万工作单位、8万个前缀和1万条输出候选；桶内查询也计入上限并响应停止。所有规则继续受本次总候选预算、时间、停止和 Saluki 排除控制，准备成本也会计入工作时间。末字节运算不适用于低60位初筛或非相符FNV域。

报告保留计划数、准备工作量及省略上界；只提高总预算不会解除各规则的生成上限。没有观察到合适模板时该规则不产生计划。增加可信明文和本作模板通常比扩大无结构字符枚举更有效。实现来源与边界见[本次更新记录](upstream-update-20261009.zh-CN.md)。

## 可选社区表：默认关闭

离线流程无需社区同步。“更多选项”中的“只读导入cod-name-db社群表”默认关闭，只有你明确开启时才同步。GUI会在估算之前单独完成首次同步或显式刷新，然后使用同一份缓存估算和计算。

缓存目录可自行选择；留空使用输出根目录下 `.community-cache`。“本次刷新社群缓存”会读取上游最新commit；未刷新时复用已经固定的commit和SHA256校验内容，不以本地文件修改时间判断新鲜度。使用安全HTTPS固定来源，新电脑无需Git。

导入按行回算：符合表级规则的行标为 `verified`；键/名称不一致的重建显示名、未知表或无效行进入 `quarantined`，只能作候选。音频表有时把 `.lnn.75.48000.all` 点尾显示为目录；2.3.0 只尝试有明确结构的有限恢复拼写，且必须重新命中该行原始键，才认定为可信种子。它不会把所有斜杠、反斜杠或下划线做全局替换后直接认证。`borrowed` 导入即使源行可回算也只作候选。来源、commit、原表和行号写入相应证据；正式导出仍排除你选择的Saluki已有项。

cod-name-db未提供LICENSE，软件不捆绑社区整表、不自动发PR、不替你提交名称。网络不可用时关闭社区选项继续离线；缓存内容被改动时显式刷新或重新选择可信副本。

## 停止、预算、复跑与方法账本

默认预算1000万候选、120分钟，数字变体末尾上限32，可在“更多选项”修改。软件自动比较前向与CPU反向剥离成本；不可逆或不适用的算法继续前向。GPU是可选后端，正式命中由CPU复核。选择自动后端时可在设备不可用时回退CPU，强制GPU发生初始化失败会明确报错。

“停止并保存”等待当前批次提交后导出；关闭运行窗口会先停止并保存再退出。达到预算或手动停止为 `partial`，已经独立验证的结果仍保留。`completed` 只表示本次生成的有限计划完成，不能证明所有名称都被穷举。

输出根目录 `.namefinder-ledger.sqlite` 保存方法账本、计划内容指纹、已扫区间及可恢复命中。再次启动会创建新 `run-*`，在相同目标、来源、算法、规则、关键词等条件下复用已扫区间，并把之前的命中重新验证恢复到本轮导出。新扫描数为0时结果不必为空；已经扫过的区间不再占用本次候选预算。

源内容、目标键集合、算法参数或生成规则改变时对应指纹失效，重新计算需要的新范围。更新游戏后重新选择或扫描新导出目录；更新索引后重新运行。不要手工编辑账本或工作库；删除账本会失去跨轮复用，但不会删除源资产。

同方法、同目标与同范围连续3次完整运行零新名称时，方法守卫默认拒绝继续。确认仍有合理目的时在“更多选项”勾选方法守卫覆盖，或命令行加 `--anyway`。该选项只覆盖零产出守卫，不绕过哈希、未知域样本、索引损坏或冲突校验。

## 输出文件与 Saluki 安装

每次运行建立独立 `run-*`，新增映射在其中的 `names-*`。输出根目录用于账本复用，运行目录用于配置、阶段报告、工作库和本轮结果。

| 文件或目录 | 用途 |
|---|---|
| `report.json` | 状态、目标与命中数、阶段、实际新扫描量、缓存及结果路径 |
| `names-*/new_names.csv` | 仅新增完整键/名称两列，无表头，可单独保存 |
| `names-*/verified.csv` | 同一新增集合 |
| `names-*/verified.cdb` | 新增集合的CDB格式 |
| `names-*/hash_pkg` | 依实际类型和profile分类的增量CDB |
| `names-*/evidence.jsonl` | 方法ID、版本、生成器SHA、profile、掩码和回算依据 |
| `names-*/manifest.json` | 源指纹、去重统计与校验清单 |
| `saluki-ready/hash_pkg` | 保留输入同名旧索引条目的合并文件 |
| `saluki-ready/merge-report.json` | 合并、条目数与冲突记录 |
| `work.sqlite` | 本轮工作库 |
| `pending-low60.csv` | 如存在，为未正式认证的截断键候选 |
| 输出根目录 `.namefinder-ledger.sqlite` | 跨轮方法与已扫区间账本 |

完整键已存在或名称原文已存在都会排除新增，即使旧键来自另一算法或截断索引。同键异名冲突不自动覆盖。大小写、斜杠和下划线不做全局互换来判断“原样名称”。

新增CSV与增量只含新项；合并目录为了保留旧数据会包含旧项，不能把它的总行数当作新发现。现代alias路由到 `fnv1a_soundbanks_aliases_v2.cdb`；骨骼FNV32对应 `fnv1a_bones.cdb`，Treyarch满64对应 `fnv1a_bones_v2.cdb`，实际60位字符串对应 `fnv1a_strings.cdb`。脚本符号等特殊域是否由你使用的Saluki版本加载仍需核对，通用CDB格式正确不代表任意池都会自动使用它。

结束后点击“打开新增CSV”，或按 `report.json` 的 `new_names_csv` 路径找到文件。零新增时CSV可能为空，按报告区分“全部已有”“关键词过滤”“未命中”“仅低60位”。验证目标数可能包含已有名称；最终输出数才是新增完整键的数量。

安装到Saluki时关闭Saluki，备份原 `hash_pkg` 同名文件，再复制 `saluki-ready/hash_pkg` 中相应文件。不要把只有新增项的分类增量直接覆盖完整旧索引。软件不自动写Saluki安装目录；自动更新也可能覆盖手工索引。

软件已做CDB格式、独立读取与合并保留验证，未将其视为Saluki GUI实时加载验收。首次复制后在自己的Saluki版本中检查名称显示。

## 液态玻璃界面与降低特效

主窗口和教程采用柔和内部背景、半透明玻璃面板、模糊与边缘高光，控件保持可读与键盘焦点。原创“哈希符号+放大镜”图标用于主程序、窗口与安装器。玻璃采样发生在应用内部，不会改变实际哈希结果；图形驱动或着色器不可用时可使用清晰面板。

右键软件快捷方式 → 属性，在“目标”原有EXE路径后加空格和 `--reduced-effects`，例如：

```text
"C:\Users\用户名\AppData\Local\Programs\CODNameFinder\CODNameFinder.exe" --reduced-effects
```

重新启动。离线教程、计算、停止和导出保持可用。许可与参考项目保存在安装目录 `THIRD_PARTY_NOTICES.md`、`licenses` 及 `docs/liquid-glass-research.zh-CN.md`。

## 安装版命令行：无需 Python 或 Git

以下在安装目录PowerShell运行。若工具路径含空格，用 `& "完整路径\CODNameFinder.exe"`。命令输出UTF-8 JSON或JSON行；必要时通过PowerShell管道保存。开发者也可用 `python -m finder` 同名命令，安装版用户直接用EXE即可。

### 一份普通动画配置

在独立数据目录保存UTF-8 `run.json`，JSON路径可用正斜杠。

```json
{
  "input_mode": "folder",
  "snapshot_file": "",
  "folder": "D:/Exports/animations",
  "indexes": "D:/NameFinderData/Indexes",
  "output": "D:/NameFinderData/Results",
  "game": "COD2026",
  "hash_domain": "asset",
  "profile": "iw-resource63",
  "asset_type": "xanim",
  "dictionary": "",
  "cross_asset": true,
  "related_folder": "",
  "borrowed_dictionary": "",
  "community": false,
  "community_cache": "D:/NameFinderData/CommunityCache",
  "community_refresh": false,
  "allow_unverified_domain": false,
  "anyway": false,
  "exclude_material": true,
  "low60": false,
  "keyword": "",
  "backend": "cpu",
  "number_max": 32,
  "budget": 10000000,
  "seconds": 7200
}
```

目录填写你自己的真实位置；选择关联明文目录时修改 `related_folder`，借用前作TXT/CSV/CDB时修改 `borrowed_dictionary`。先估算，再执行：

```powershell
.\CODNameFinder.exe run "D:\NameFinderData\run.json" --estimate
.\CODNameFinder.exe run "D:\NameFinderData\run.json"
.\CODNameFinder.exe methods report "D:\NameFinderData\Results"
```

`estimate` 子命令也可使用。仅估算不保存扫掠或提交正式运行；它仍读取输入并做有限本机基准。社区缓存未建立或配置要求刷新时，只读估算会要求先同步。

```powershell
.\CODNameFinder.exe estimate "D:\NameFinderData\run.json"
.\CODNameFinder.exe run "D:\NameFinderData\run.json" --anyway
.\CODNameFinder.exe devices
```

### 捕获当前已加载集合

先查看所选目录的实例，确认作品和PID，再只读捕获。没有 `--launch` 时不会启动或加载任何内容。

```powershell
.\CODNameFinder.exe cordycep status --directory "D:\_tiqu\Cordycep"
.\CODNameFinder.exe cordycep capture --directory "D:\_tiqu\Cordycep" --game COD2026 --output "D:\NameFinderData\Captures"
```

成功结果的 `snapshot_file` 是应选择的输入路径。CLI在 `--output` 下新建 `capture-*` 子目录；GUI在结果目录下的 `captures` 子目录保存。需要从多实例中明确指定时：

```powershell
$loaderStatus = .\CODNameFinder.exe cordycep status --directory "D:\_tiqu\Cordycep" | ConvertFrom-Json
$loaderStatus.instances | Select-Object pid, game_id, game_dir
$loaderPid = [int](Read-Host "输入上面属于所选作品的 PID")
.\CODNameFinder.exe cordycep capture --directory "D:\_tiqu\Cordycep" --game COD2026 --pid $loaderPid --output "D:\NameFinderData\Captures"
```

### 启动一个本软件管理的新实例

先用 `scripts` 列出所选目录根的 BAT 文件。所选目录没有正在运行的 Cordycep CLI 时，使用 `--launch --script` 真正运行指定文件，以该 Cordycep 目录作为工作目录。`--script` 只填目录根文件名，不填绝对路径或子目录；省略时按作品使用 `RunMW7Beta.bat` / `RunBO7.bat`。

```powershell
.\CODNameFinder.exe cordycep scripts --directory "D:\_tiqu\Cordycep"
.\CODNameFinder.exe cordycep capture --directory "D:\_tiqu\Cordycep" --game COD2026 --launch --script "RunMW7Beta.bat" --output "D:\NameFinderData\Captures"
.\CODNameFinder.exe cordycep capture --directory "D:\_tiqu\Cordycep" --game BO7 --launch --script "RunBO7.bat" --output "D:\NameFinderData\Captures"
.\CODNameFinder.exe cordycep capture --directory "D:\_tiqu\Cordycep" --game COD2026 --launch --script "自选 中文启动.bat" --output "D:\NameFinderData\Captures"
```

上面是独立操作示例，每次只选择实际需要的一条。`自选 中文启动.bat` 是文件名示例，需替换为 `scripts` 返回的真实文件。启动读取集合由 BAT 决定，不隐式发送 `loadall`。COD2026的 `RunMW7Beta.bat` 已通过本次新 CLI 现场验证；BO7的 `RunBO7.bat` 未返回可核对的完成提示，仍未现场通过。用户也可先手动加载后使用不带 `--launch` 的读取方式。目录中已有 CLI 时软件拒绝重复启动，包括仍在初始化、尚无状态文件的进程。

`--load-all` 只可与新实例 `--launch` 一起使用；这是显式请求更多加载，不提供全游戏完整性保证。用户已有实例应先自行加载所需内容，再按上一节读取。

```powershell
.\CODNameFinder.exe cordycep capture --directory "D:\_tiqu\Cordycep" --game COD2026 --launch --script "RunMW7Beta.bat" --load-all --output "D:\NameFinderData\Captures"
```

### 用增强快照进行离线计算

将完整捕获目录复制到 `D:\NameFinderData\Snapshots\MW7-common`，在同一数据目录保存UTF-8 `snapshot-run.json`。`folder` 在快照模式留空，`snapshot_file` 是实际增强manifest，不能填 `records.csv`、`strings.txt` 或任意JSON。

```json
{
  "input_mode": "snapshot",
  "snapshot_file": "D:/NameFinderData/Snapshots/MW7-common/snapshot.json",
  "folder": "",
  "indexes": "D:/NameFinderData/Indexes",
  "output": "D:/NameFinderData/SnapshotResults",
  "game": "COD2026",
  "hash_domain": "asset",
  "profile": "iw-resource63",
  "asset_type": "xanim",
  "backend": "cpu",
  "cross_asset": true,
  "dictionary": "",
  "related_folder": "",
  "community": false,
  "exclude_material": true,
  "low60": false,
  "keyword": "",
  "budget": 10000000,
  "seconds": 7200
}
```

```powershell
.\CODNameFinder.exe run "D:\NameFinderData\snapshot-run.json" --estimate
.\CODNameFinder.exe run "D:\NameFinderData\snapshot-run.json"
.\CODNameFinder.exe methods report "D:\NameFinderData\SnapshotResults"
```

同规则的全部已适配非模型类型可将 `asset_type` 改为 `auto`；分别找声音、银行或动画包可改为 `sndasset`、`soundbank`、`animpkg`。BO7现代快照改 `game` 为 `BO7`，路径填BO7增强快照，资源仍为 `asset / iw-resource63`。

原项目BO4/BOCW旧快照改 `snapshot_file` 为真实 `.ids` 路径、`game` 为对应作品、`profile` 为 `fnv1a63`，选择其已有证据支持的资源类型。与 `.ids` 同名的 `.pools.txt` 放在旁边，软件兼容定宽文本及三列CSV，并核对记录计数。现代 `.ids` 缺少增强build证据，不能靠改游戏名或池标签成为可计算的新作快照。

### 社区同步与隔离导入

`community sync` 是显式联网操作；输出的 `csv_dir` 为本次固定commit下的实际目录。用命令返回的实际值，不要把缓存根目录误当CSV目录。

```powershell
.\CODNameFinder.exe community sync "D:\NameFinderData\CommunityCache"
.\CODNameFinder.exe community sync "D:\NameFinderData\CommunityCache" --refresh
.\CODNameFinder.exe community import "D:\NameFinderData\CommunityCSV" --profile iw-resource63 --output "D:\NameFinderData\CommunityImport"
.\CODNameFinder.exe community import "D:\NameFinderData\PriorTitleCSV" --borrowed --output "D:\NameFinderData\BorrowedImport"
```

这里 `CommunityCSV` 是你复制的CSV目录示例；使用同步缓存时改成sync返回的 `csv_dir`。导入汇总报告统计 `verified`、`quarantined`、`borrowed`，`--output` 将三种记录分别保存为JSONL供检查；它们不直接变成Saluki安装包。

要在运行中使用已同步表，把配置 `community` 改为true，`community_cache` 填上述缓存根目录，`community_refresh` 保持false，再执行估算和运行。需要更新时先显式sync `--refresh`。GUI会替你做“同步 → 只读估算 → 确认运行”的步骤。

### 表考古：判断某张表采用的规则

```powershell
.\CODNameFinder.exe table-audit "D:\NameFinderData\CommunityCSV" --profile iw-resource63 --profile fnv1a64 --filter rex
.\CODNameFinder.exe table-audit "D:\NameFinderData\CommunityCSV" --sample-limit 1000
```

输出逐表、每个候选profile、路径/名称族的回算数量、比例与有效位宽。未指定profile时尝试已注册规则；`--sample-limit` 明确标记抽样不完整，不是整表证明。表内大量重建显示名回算失败不意味着发现新算法，也不能把零样本组推定为已证实。

### 特殊名称域配置

声音银行别名：将 `hash_domain` 设为 `soundbankalias`，`asset_type` 设为 `soundbankalias`，现代 `aliases_v2` 选择 `fnv1a64`，不要沿用资源的IW63。

MWII / MWIII骨骼用 `hash_domain: "bone"` 与 `profile: "fnv1a32"`；BO6 / BO7骨骼用 `hash_domain: "bone-v2"` 与 `profile: "fnv1a64"`，`asset_type` 均为 `bone`。BOCW真实60位字符串域可使用 `hash_domain: "bone"` 对应登记标签并核对规则；域ID与作品下拉的可用项一致，不能跨作品套用。

未证实COD2026 Dvar的JSON选项例子如下，其他必填路径仍按普通配置补齐：

```json
{
  "game": "COD2026",
  "hash_domain": "dvar",
  "profile": "iw-dvar64",
  "asset_type": "dvar",
  "dictionary": "D:/NameFinderData/Samples/cod2026-dvar-real-pairs.csv",
  "allow_unverified_domain": true,
  "low60": false,
  "borrowed_dictionary": ""
}
```

这个片段不是已证实的COD2026算法声明，必须有至少3个对应类型的本次完整目标样本回算成功。脚本符号选 `script` / `scriptfield`，Omnvar选 `omnvar` / `omnvar`，骨域unknown也须相同类型的完整样本，不能拿动画证据解锁。

## 常见问题排查

| 现象 | 优先检查 |
|---|---|
| 新电脑没有研究项目或运行时 | 使用完整EXE安装包，保留engine目录即可 |
| 没有CDB索引 | 复制实际Saluki的hash_pkg，示例库不能替代正式索引 |
| 找不到计算后端 / 注册表不一致 | 退出软件，重新安装完整同版本包；不要混用旧DLL或单独主程序 |
| 识别后没有所选类型 | 看明确前缀和detected_type_counts，调整类型或整理文件夹 |
| sndbank / animpkg导入报错 | 检查 `sndbank_<hex>` / `animpkg_<hex>` 前缀和所选类型，更新到2.3.0 |
| 快照缺文件或SHA不一致 | 重新复制整个capture目录，保持manifest与附件原样；不要手改SHA |
| 现代IDS提示缺少池清单 | 将同名 `.pools.txt` 与 `.ids` 放在一起，不能借用其他作品或实时池号 |
| 现代IDS alias无法按full64导入 | v1已丢最高位，改用保留原始64位键的受支持输入；不能只靠低63位认证 |
| 快照所属作品不一致 | GUI选择快照记录的作品，不能把COD2026与BO7互换 |
| 快照没有所选类型 / 算法目标 | 选已适配类型与asset / iw-resource63；嵌套alias、骨骼等不是通用node目标 |
| Cordycep 状态属于另一PID | 等待加载稳定；只读指定目录中实际实例，多实例用CLI --pid |
| 配置或模块与登记版本不同 | 需要对应build的适配资料；不能只按文件名或版本号强套旧池编号 |
| 读取内存权限不足 | 使工具与用户所选加载器的本地权限相匹配，核对可执行文件所在目录 |
| BAT 下拉为空 / 文件已删除 | 选择包含 BAT 的 Cordycep 目录；点击“刷新 BAT”，只列目录根文件，不列子目录或 CMD |
| BAT 启动作品不匹配 / 加载超时 | 运行前核对所选脚本、作品、游戏路径与依赖；也可自行启动加载后用读取按钮 |
| 拒绝重复启动但尚无已加载实例 | 同目录 CLI 可能正在初始化；等待加载完成后读取，不要同时启动另一个 BAT |
| BO7新启动没有完成提示或可用状态 | 本次新构建现场未通过且原因未确认；手动RunBO7并确认加载后读取，不影响离线计算 |
| 未证实域解锁失败 | 至少3个不同完整目标键、同域同类型、可信真实名称、选对profile；借用与低60位不可解锁 |
| 估算要求先同步社区缓存 | CLI先community sync；GUI明确勾选社区后会独立同步；离线可关闭 |
| 关联选项变灰 | 核对所选类型是否有规则；2.3.0支持动画、声音、声音库、alias、图片／材质及自动识别范围 |
| GPU不可用 | 检查OpenCL驱动，或选择CPU；强制GPU失败不会伪装为成功 |
| 新扫描0次但有输出 | 相同内容的已扫区间命中已恢复，属于正常复用 |
| 输出0项 | 查看未命中、Saluki已有、关键词过滤、仅低60位、有限计划覆盖是否完成 |
| 方法守卫拒绝 | 同范围连续3次完整运行零新增；需要继续时明确使用anyway |
| 名称计算partial状态 | 本轮停止或预算耗尽，保存结果后可用同输出根目录重跑未扫范围 |
| 捕获partial状态 | 已适配范围不稳定或停止，只作诊断；保持加载器稳定后重新捕获 |
| whole_snapshot_stable=false但complete=true | 未知诊断池可变，正式范围仅已适配非模型池；不表示全游戏完整 |
| sleep length must be non-negative | 停止旧版并安装2.3.0；该节流时间边界已经修复 |
| 玻璃显示异常 | 追加 --reduced-effects 后重启 |
| 无法找齐全部名称 | 补充可信本作词典和模板；哈希无法直接读取原文，有限搜索不保证全覆盖 |

首次建议按“示例 → 自己的完整动画键 → 关联线索 → 按需要的借用/社区/特殊域”的顺序增加输入。每次保留报告、证据和完整输出目录，方便判断新增线索是否增加产率。
