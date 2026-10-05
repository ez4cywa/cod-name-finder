# 本地 Cordycep 捕获接入核验

调查日期：2026-10-05。对象为 `D:\_tiqu\Cordycep` 的 Cordycep 2.9.0.0。本文记录本机实测与静态文件事实，供独立只读捕获组件使用；这里的 PID、地址和文件哈希不适用于另一台电脑或另一个游戏 build。

本次没有启动加载器或游戏，没有运行 BAT，没有调用转储内的函数，没有修改 Cordycep 文件。未读取授权文件、隐藏的授权辅助文件或密钥。类型枚举来自本地配置指定的游戏转储，不复制第三方捕获实现或分发游戏转储。可部署的事实映射保存在 `finder/cordycep_profiles.json`。

## 当前实例归属

本机只有一个匹配的 `Cordycep.CLI.exe`，PID **35728**，父进程号 **36688**，可执行文件为 `D:\_tiqu\Cordycep\Cordycep.CLI.exe`，文件版本与产品版本均为 **2.9.0.0**。进程创建时间为 2026-10-02 15:28:41 +08:00。命令行只做内部匹配，确认提及状态文件中的游戏目录；没有记录或输出完整命令行。

`Data/CurrentHandler.json` 的 `pid` 与该实例相符。`game_id` 为十进制 `15571564309532493`，按 uint64 小端拆成八个 ASCII 字节是 `MODWAR7\0`。识别时只去掉尾部 NUL，得到 **MODWAR7**；此本地 handler 对应用户的 **COD2026 Beta**，不能将这个内部代号解释成公开旧仓库的 MW2019 handler。

| 状态字段 | 本机记录 |
|---|---|
| `game_dir` | `F:\BaiduNetdiskDownload\Modern Warfare 4 - Beta` |
| `game_module_path` | `D:\_tiqu\Cordycep\Data\Dumps\cod26-cod_dump.exe` |
| `pools_addr` | `0x201bb521248` |
| `strings_addr` | `0x201bd04b000` |
| `str_pool_size_addr` | `0x201bb4ffc38` |
| `flags` | `beta` |

运行中的转储模块基址为 `0x7ff697e50000`，映像大小为 359,264,256 字节。地址来自当前实例，必须在每次捕获时重新读取，不能硬编码。

`RunMW7Beta.bat` 的安全字段为 handler `mw7`、标志 `beta`，游戏目录与上述 JSON 相同。`RunBO7.bat` 的安全字段为 handler `bo7`，游戏目录为 `D:\xboxgame\Call of Duty\Content`。这里只解析字段，没有执行脚本。

## 状态协议与公开捕获器的差异

公开捕获器接受 JSON 的 `pid`、`game_id`、`pools_addr`、`strings_addr`；只有 PID 匹配才使用。CLI 的 CSI 文件至少需要 24 字节：八字节游戏标识、uint64 小端池地址、uint64 小端字符串地址。公开实现不使用 CSI 后续字节。[状态解析源码](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/cordycep.rs#L463)

本地 JSON 有额外的游戏目录、模块路径、字符串池大小指针和 flags。**本地 CLI 也写出 JSON**，因此应优先选取与指定 PID 匹配的 JSON；CSI 自身没有 PID，不能单独证明实例归属。

本地 CSI 为 87 字节，其前 24 字节与 JSON 的游戏 ID、池地址和字符串地址逐字节一致。剩余部分实测完整解码为：

| 顺序 | 类型 | 本机值 |
|---|---|---|
| 1 | uint32 小端：目录 UTF-8 字节数 | 47 |
| 2 | 对应数量的 UTF-8 字节 | 与 JSON `game_dir` 完全相同 |
| 3 | uint32 小端：flags 数量 | 1 |
| 4 | uint32 小端：第一个 flag 字节数 | 4 |
| 5 | 对应数量的 UTF-8 字节 | `beta` |

解析恰好消耗全部 87 字节。**CSI 尾部不是字符串池大小指针**；不能把 flags 数量及长度拼成 uint64 地址。该扩展仅确认本地 2.9.0.0 的当前状态样本，适配器应对长度、数量、UTF-8、尾部边界做检查，不假定其它发行版完全相同。

## 资产池与节点前缀

公开池定义含五个指针字段；公开读取器按 512 个池、每池 40 字节读取。公开资产节点在拥有者指针之后还有其它成员，捕获器实际读取的是前 **96 字节**，不应将 96 字节声称为全部 C++ 对象大小。[池定义](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/src/Parasyte/XAssetPool.h)、[节点定义](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/src/Parasyte/XAsset.h)、[读取前缀](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/cordycep.rs#L108)

| 结构 | 字节偏移 | 字段 |
|---|---|---|
| 池 | 0 / 8 / 16 / 24 / 32 | root / end / lookup_table / header_memory / asset_memory |
| 节点前缀 | 0 / 8 / 16 / 24 | header / temp / next / previous |
| 节点前缀 | 32 / 40 / 48 | raw_id / kind / header_size |
| 节点前缀 | 56 / 64 | extended_data_pointer_offset / extended_data_size |
| 节点前缀 | 72 / 80 / 88 | first_child / last_child / owner |

项目捕获负责人对本机 PID 35728 使用 WinAPI 只读验证：池记录 40 字节、节点前缀 96 字节可正常读取；root 是 `header=0 / raw_id=0 / kind=0xffffffff` 的哨兵，实际项从 root.next 开始。已核对池 **0、6、7、10、14、26、27、63、64、66、87、110、186** 的首个实际节点，其 kind 等于所在池号。池 6 样本 `raw_id=02bcedeb74a4d7c4 / header_size=144`；池 186 样本 `raw_id=26b1f6bc2fe84b82 / header_size=64`。

这证明当前实例支持该公共前缀，但不能免除每次捕获的检查。必须保留链表循环、坏指针、读取不足、状态变化及节点类型不符的错误；任何失败都应明确标记 partial，不生成“完整游戏”结论。条目数超过某个阈值也不能证明所有 fast file 已加载。

后续只读捕获负责人报告：本次诊断集合包含 **414,913 个原始 key 条目**及 **48,974 条候选字符串**；下面列出的全部 **16 个已映射池**在重复捕获中稳定。未知池 42、76、127、128、381 等仍有变化。因此 `complete` 必须限定为“当前加载集合中已适配的非模型资产范围”，同时单独记录 `whole_snapshot_stable=false`。未知池诊断中的不稳定 key 永远不参加名称计算，不能将已映射范围的稳定性扩展为所有池稳定或完整游戏。

字符串大小指针本机实读 uint64 值为 **1,625,161**；对应内存区域可读范围为 **33,558,528** 字节。适配器优先使用受边界限制的实际大小，不把整个可读虚拟内存区域都当作字符串内容。字符串池文本只能作为候选；仍须按名称域哈希并匹配实际目标才能输出名称。

## 从本地类型表建立映射

`PoolInfo` 只有空的 `mw7` 目录，当前没有现成的 pool census 或映射文件。不能使用 hash-slinging-slasher 的 BO4/CW 数组替代新作枚举。

COD2026 Beta 配置 `CoDMW7HandlerBeta.toml` 明确给出 `XAssetTypeNames` 定位签名：

```text
4C 8D 35 ?? ?? ?? ?? 48 8D 35 ?? ?? ?? ?? 4C 8D 3D ?? ?? ?? ?? C5 C8 57 F6
PatternType = Variable
PatternFlags = ResolveFromEndOfData
Offset = 3
```

在指定的本地 `cod26-cod_dump.exe` 中匹配唯一一处：文件偏移 `0xb400c93`、RVA `0xb401893`。从指令里的 disp32 按 RIP 规则解出类型名指针表 RVA **0xc8018a0**，文件偏移 **0xc800ca0**。通过 PE 节映射与原 ImageBase 解引用，可连续读到 **414 个合法 ASCII 类型名**。这是静态读取，不调用游戏函数。当前实例中同表地址为模块基址加 RVA，即 `0x7ff6a46518a0`。

BO7 正式配置指定 `cod_dump.exe`，从 `xanim` 字符串的绝对指针引用核对同一组连续类型名，可定位表 RVA **0xb2c5a10**、文件偏移 **0xb2c4c10**，共 **408 项**。这一表的关键枚举与当前 COD2026 Beta 相同，但 BO7 本次现场没有形成成功的已加载状态，运行验证应在用户手动实际加载后进行。加载器包含八字节字面量 **BLACKOP7**，未找到 `BLKOPS07`；映射文件注明其为静态候选证据，不能声称读取过 BO7 的 CurrentHandler 状态。

| pool | 类型表名称 | 本软件 kind | 默认算法 / 名称域 |
|---|---|---|---|
| 6 | xanim | xanim | iw-resource63 / asset |
| 10 | material | material | iw-resource63 / asset |
| 14 | image | image | iw-resource63 / asset |
| 26 | soundbank | soundbank | iw-resource63 / asset |
| 27 | soundbanktransient | soundbanktransient | iw-resource63 / asset |
| 55 | localize | localize | iw-resource63 / asset |
| 56 | attachment | attachment | iw-resource63 / asset |
| 57 | weapon | weapon | iw-resource63 / asset |
| 63 | rawfile | rawfile | iw-resource63 / asset |
| 64 | gscobj | scriptfile | iw-resource63 / asset |
| 65 | gscgdb | scriptfile | iw-resource63 / asset |
| 66 | stringtable | stringtable | iw-resource63 / asset |
| 87 | animpkg | animpkg | iw-resource63 / asset |
| 110 | scriptbundle | scriptbundle | iw-resource63 / asset |
| 116 | keyvaluepairs | keyvaluepairs | iw-resource63 / asset |
| 186 | sndasset | sndasset | iw-resource63 / asset |

每条目都绑定确切的模块和配置哈希，并要求运行时 node.kind 与池号相符。`mapping_status=runtime_structure_verified` 只用于当前 COD2026 Beta 中实际核对过的池；其它条目是静态表证据，要求捕获时检查。即使 node.kind 正确，只要模块或配置文件哈希发生变化，仍应重新建立标签映射。

pool 7 为 xmodelsurfs，pool 8 为 xmodel，均列入模型排除池。pool 73 是 **scriptable**，没有映射为 scriptbundle。

**21 个软件类型不会强行各分配一个池。** structuredtable 在这些表中没有对应项；soundbankalias、bone、scriptfield、dvar 的名称哈希通常需要独立的内部结构解析，泛用池节点不提供这些嵌套名称。表中 COD2026 的 347=`omnvar`、355=`omnvarlist`，BO7 的 348=`omnvar`、356=`omnvarlist` 是资源资产对象；其 node ID 不能直接当作 Omnvar 符号的 secure 哈希。上述类型保持未映射，保留原 key/pool 元信息，不给出默认名称算法。

BO7 Beta 配置指定的 `cod25-cod_dump.exe` 有 **367 项**，表 RVA **0x9a0a800**。例如 soundbank=27、soundbanktransient=28、rawfile=65、animpkg=89、sndasset=192，已经与 BO7 正式不同。因此本次机器映射只包含 BO7 正式和 COD2026 Beta，不以 BO7 Beta 表填充正式版。

## BO7 独立实例的启动文件要求（只读核查）

本机 `D:\xboxgame\Call of Duty\Content` 存在，`Content\cod25` 对应正式 BO7 配置的 `FilesDirectory=cod25`。目录内递归检出 **43,684 个 .ff**、合计 **15,239,418,488 字节**，以及 **111 个 .xpak**；.ff 位于 cod25 根及 lpc 子目录。这里只做目录和文件长度检查，不解析游戏数据或启动加载器。

正式配置声明的 **19 个 CommonFiles 均存在对应根目录 .ff**：boot、code_pre_gfx、code_post_gfx、code_reloadable、frontend_ui_boot、frontend_ui、global、global_stream_mp、global_shared_mp、global_base_mp、global_stream_cfwd_mp、ingame、ingame_shared_mp、ingame_base_mp、ingame_mp、ingame_br、ingame_bm、ingame_zm、ingame_ob。文件存在并不证明压缩数据完整、handler 与版本匹配，或初始化必然成功。

| 普通运行支持文件 | 只读检查 |
|---|---|
| Cordycep.CLI.exe | 存在，18,040,832 字节 |
| Data/Configs/CoDBO7Handler.toml | 存在，12,849 字节 |
| Data/Dumps/cod_dump.exe | 存在，598,475,776 字节 |
| Data/Dumps/cod_dump.cache | 存在，2,136 字节 |
| Data/Deps/oo2core_8_win64.dll | 唯一配置依赖，存在，962,048 字节 |
| Data/Aliases/BlackOps7Aliases.json | 不存在 |

上述配置指定的转储、缓存和依赖足够做启动条件检查，不必复制整个 3.43GB 的 Data/Dumps 目录。加载器、其 GPL 许可证、BO7 配置、所选转储/缓存及单一 Oodle 依赖的普通文件合计 **617,528,533 字节**，约 **589MiB**。这是普通文件下限，不构成对实际发行版其它运行要求的保证；授权相关内容不在本次读取范围内，也不能进入本软件安装包。

BO7 的别名 JSON 缺失，当前已成功加载 MW7 的对应别名 JSON 同样缺失。公开 GameHandler 在别名文件打不开时返回 false；从这些事实可推断别名文件不必然阻止基本初始化，但 BO7 实际行为仍须现场验证，不能凭旧版源码保证。[公开别名加载行为](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/src/Parasyte/GameHandler.cpp#L117)

两个实例如需并行，必须使用独立的加载器目录和工作目录，避免共用 CurrentHandler、Log、cache 等输出。原 BO7 BAT 仅声明 sethandler/init，没有 loadall；自动启动后也不得把 common 集合称为全部 BO7。当前用户既有 MW7 进程无需关闭或替换。

后续运行负责人在隔离本地目录尝试 BO7 新实例：子进程立即以0退出，没有形成 console、Log 或 CurrentHandler；两种隐藏进程窗口方式均未成功初始化。复制过程中仅使用既有授权内容的本地不透明副本，没有解析内容或绕过，也没有关闭用户现有 PID35728 的 MW7 实例。结论为 **BO7静态映射已登记，现场启动未通过，捕获支持尚未实证**，不能猜测具体失败原因。产品应显示友好错误，指向用户手动RunBO7并确认加载后读取的路径。

较新的 MW7 快照 `validation/cordycep-live/capture-20261005-175437-52080a/snapshot.json` 实读511,153个raw条目和104,640条候选字符串；严格读入排除材质后的305,294个已适配目标，其中xanim为40,134个。此前414,913/48,974的数字是较早一轮集合，并不是必须匹配的完整游戏总量。当前范围仍以逐池稳定性和manifest为准。

## 文件指纹与复核边界

| 文件 | SHA-256 |
|---|---|
| Cordycep.CLI.exe | fe43506a599fd84472c81599ace976b6ee6cde8b545745ea7ff0e3046fe1e1e7 |
| CoDMW7HandlerBeta.toml | 3456739384d434ce14e0f77f044c6539959bf6f98737bfdd5c04899f85530f31 |
| cod26-cod_dump.exe | 428309e60147007e26a86b329fea6703ebd0bce6937aa6c5fa17fda4ed89f7b5 |
| CoDBO7Handler.toml | 2243f645db9804ec2ab8f1a7cd4ab1872a8d122af207945e823343845665883a |
| cod_dump.exe | 6ccc9ef5af213d9047f64a5a1212d06047ecc008eeb56f17ef6841511ff1fc4a |
| CoDBO7HandlerBeta.toml | b9ea613b7e11f2d1ec0269d6a3069f80eb262347388946a39b9c6c201f02ce65 |
| cod25-cod_dump.exe | ed599bef9bdda8d1bccf43bab447bda106e88ee77dd32fd0ac5eecbea74f32a3 |

原始 key 按 **64 位无符号值**保存，随后按已核验名称域使用比较掩码。公开 snapshot 入口会对所有 key 使用统一的 `ID_MASK` 后再写 `.ids`，并沿用共享 POOLS 标签；本接入不能照搬这一做法，否则可能丢失 full64 域的最高位或给新作错误标签。[上游 snapshot 入口](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/bin/snapshot.rs#L50)

`cordycep_profiles.json` 中 `stored_mask=7fffffffffffffff` 表达已知资产名称的比较范围，**不授权修改捕获的原始 key**。未知池保留 64 位 key 和数字池号，等待新的映射证据。没有确认载入全游戏时，只能称为“当前已加载集合”，匹配成功证明存在于该集合，匹配失败不能证明资产不存在。

此接入使用用户现有 Cordycep 安装；软件安装包不包含 Cordycep、游戏模块、授权文件或第三方社区全库。运行时只申请读取和查询权限，拒绝游戏主进程和路径冒充，不写加载器内存、不调用其模块代码。公开项目的 GPL 边界另见 `docs/capture-feasibility.zh-CN.md`，协议事实和枚举表不等于允许直接复制其实现。
