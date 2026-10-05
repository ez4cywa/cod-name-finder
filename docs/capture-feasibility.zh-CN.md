# 原项目捕获功能接入可行性与 2.2.0 实现状态

日期：2026-10-05。本文保留最初的上游源码调查，并更新到本软件2.2.0的独立实现状态。最初的可行性调查没有运行加载器；随后已对用户现有的本地COD2026 Beta实例完成只读验证。BO7静态适配与文件条件已核对，但隔离启动现场未通过，尚未证明可现场捕获；应先手动运行RunBO7并正确加载，再只读验证。不推定未确认的失败原因。

**已引入离线快照导入与可选Cordycep捕获。** 新电脑仍只需安装工具、提供完整快照及自己的名称索引；拥有兼容加载器和游戏文件的电脑承担捕获。捕获扩大目标集合，不会直接解出名称，后续候选生成、独立回算、Saluki去重和CSV/CDB导出保持原流程。使用步骤见随安装包提供的 [一键教程](user-guide.zh-CN.md)，详细本地事实见 [状态与池核验](cordycep-local-research.zh-CN.md)。

## 核实的上游接口

本次固定 hash-slinging-slasher commit `10108fa4c54509989143e8c8028c7a76ab57d28a`。捕获程序是 `snapshot`，构建feature `cordycep` 默认关闭；启用后引入Windows API及状态文件解析依赖。程序的可选第一个位置参数为输出`.ids`路径，未给出时用游戏ID生成文件名；先由用户在Cordycep加载游戏数据，源码提示使用其`loadall`。[构建入口](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/Cargo.toml)、[snapshot入口](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/bin/snapshot.rs)

捕获器读取Cordycep窗口版或CLI版进程。窗口版状态JSON包含进程ID、游戏ID、资产池及字符串池地址，并核对进程ID；CLI版二进制状态文件至少24字节。随后遍历512个池的链表，跳过临时占位项。这不是直接扫描正在运行的游戏，也不是对游戏进程注入代码。[加载器适配](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/cordycep.rs)

读内存调用申请 `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION` 并使用 `ReadProcessMemory`；未申请写进程内存权限。源码在打开失败时提示尝试管理员权限，因此不能断言所有机器都必须管理员运行。同用户且权限允许时可只读，权限不足或加载器以较高权限运行时需要相应权限。后续组件只读用户选择的加载器，权限不足明确报错，不自动提高权限。[进程读取](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/memory.rs)

## 快照格式与直接复用的边界

`.ids`版本1是小端二进制，不是CSV：6字节魔数 `CODIDS`、uint16版本1、uint16游戏标识长度、标识UTF-8字节、uint64记录数量；每条记录为uint64键和uint16池号，共10字节。总长度为 `18 + 标识字节数 + 10 × 记录数`。写入时按键/池号排序并去重，相同键在不同池仍保留。[格式实现](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/snapshot.rs)

固定上游commit中BO4快照为1,153,208条、BOCW为1,677,099条，游戏标识分别对应其公开文件。**这是原仓库已提交快照的范围，不是本软件2.2.0捕获适配的上限。** 该commit未提交MWII至COD2026快照。其`.pools.txt`为带标题的定宽文本，而当前上游writer生成三列CSV；本软件独立导入兼容这两种，并核对计数与数字池事实，不靠显示标签推断类型。[BO4池清单](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/snapshots/blkops04.pools.txt)、[BOCW池清单](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/snapshots/blkopscw.pools.txt)、[已提交快照目录](https://github.com/KingslayerKyle/hash-slinging-slasher/tree/10108fa4c54509989143e8c8028c7a76ab57d28a/snapshots)

两处不能原样迁移：

- 捕获时强制清除最高位。文件字段虽然是uint64，数据已只保留63位；对要求满64位的现代alias / bones等域不能据此做完整键认证，也不能靠候选回算“补回”丢失的证据。原样导入适用于已确认按63位存储的资源域；特殊域需要保留原始完整键的新版捕获来源。
- 当前捕获入口给池号打印名称时使用全局ColdWar池表，虽然库内另有BO4池表。新作池号不能直接照这些标签映射；未知池保留编号，须用对应游戏/build资料校准后才能分类。

上述均由当前入口和共享常量直接核实。[捕获掩码与标签调用](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/bin/snapshot.rs#L55)、[共享掩码与游戏池表](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/src/lib.rs)

另外，捕获器用10万条阈值拒绝明显尚未加载完全的状态；这个阈值只是启发式，超过阈值不证明所有fast file完整加载。读失败也可能提前终止池遍历。后续必须记录加载文件范围和逐池读错误，并对比稳定的两次计数；未知快照只证明“当前加载集合”，不证明整个作品全部资产。

## Cordycep依赖与新作局限

Cordycep负责使用本地游戏可执行代码加载游戏数据，捕获器只读取其池。公开README说明其内部会调整并利用游戏可执行代码完成加载；所以“捕获器只读”不等于“整个加载过程没有处理游戏代码”。用户需自己的合法游戏文件及与具体build匹配的handler/配置。构建Cordycep需其C++工具链与vcpkg；使用预构建加载器时不必在普通计算电脑安装编译器。[Cordycep说明](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/README.md)

公开Scobalula仓库固定到 `3be1e21221c61f3f021346996f4b17586e18ad4d`。其中 `CoDMW4Handler` 明确指MW2019，`CoDMW5Handler`指MWII 2022，`CoDMW6Handler`指MWIII 2023；**不能将代码名MW4理解为COD2026**。本次公开树未找到BO6、BO7或COD2026的明确handler；仓库自身提示外部发布信息可能较GitHub更新，因此不能从此推定其它发行版本绝对不支持，也不能承诺新作捕获可直接使用。[MW2019声明](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/src/Parasyte/CoDMW4Handler.h)、[MWII声明](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/src/Parasyte/CoDMW5Handler.h)、[MWIII声明](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/src/Parasyte/CoDMW6Handler.h)

已有COD2026名称样本只证明哈希算法，不能替代加载器验证。本软件另行核对了用户本地Cordycep2.9.0.0、MODWAR7状态、精确模块/配置指纹与40字节池记录、96字节节点前缀，得到了当前COD2026 Beta加载集合的运行证据。BO7的408项类型表及正式配置已核对，367项的BO7 Beta表没有套到正式版；隔离新实例立即退出，没有console、Log或CurrentHandler，现场未通过。没有解析授权或绕过加载器，也没有关闭用户原MW7实例；不能从这些现象猜测具体原因。换build需重新适配，不扩大为所有同名版本自动支持。

最近MW7实读快照为 `validation/cordycep-live/capture-20261005-175437-52080a/snapshot.json`，包含 **511,153 个raw条目、104,640条候选字符串**。独立格式读入得到 **305,294个排除材质后的已适配目标**，其中 **40,134个动画目标**。这项证据证明当前已加载范围可移交离线计算，不证明整款游戏完整或全部字符串是真实名称。资产名称的正式输出仍单独接受CPU回算、既有索引去重与发布验收。

同集合动画试跑预算为100万候选：匹配29,967项，排除Saluki已有29,311项，新增输出 **656项**。656项均独立CPU回算一致，通用verified.cdb与分类xanims_v2.cdb都经独立Rust `cdb-inspect` 逐项验收；记录在 `validation/snapshot-real-verification.json`。这是此快照与来源配置的真实试跑结果，有限预算没有覆盖全部未知动画，也没有执行Saluki GUI实时名称加载验收。

## 2.2.0 已实现的接入边界

**离线导入。** 独立读入器支持CODIDS v1和本软件CODSNAP2增强manifest，核对格式、边界、作品、排序、同池重复、数量、附件SHA256及登记的build/池映射。旧版63位证据不会提升成full64。增强快照原样保留raw64，按池的已证域与掩码做比较。原始记录及类型过滤状态进入工作库；未知池、模型与不兼容域不会变成正式目标。后续沿用估算、Saluki按类型差集、方法账本、CPU/GPU、独立回算和增量输出。

**可选捕获。** GUI及EXE命令行提供现有实例只读捕获和新实例启动。读取已有实例不发送加载、卸载或退出命令；新启动实例从指定本地脚本解析受支持的Cordycep命令，加载common并捕获。CLI的显式loadall请求不等于全游戏加载成功。组件只读用户选择的加载器状态与池，不写进程内存或调用模块函数。运行资料与普通离线计算分离，捕获完可在没有游戏、Cordycep或研究项目的新电脑使用完整目录。

现代资产适配范围为**16个非模型池、15种类型**，脚本对象/调试文件都归scriptfile资源域。未知池只保留诊断，嵌套alias、骨骼、脚本符号、Dvar及Omnvar不按通用node ID推定。`complete`仅表示当前加载集合中的已适配范围稳定，`whole_snapshot_stable`另列所有诊断池状态。字符串池只生成候选；必须命中真正目标并独立回算才输出名称。停止或范围读取失败生成partial，读入器拒绝它进行正式计算。

增强输出为snapshot.json、records.csv、strings.txt及池报告，同时生成明确损失最高位的旧工具交换.ids。安装包保留原文件夹功能、离线教程及F1入口，不包含Cordycep、游戏模块、授权内容、上游全快照或社区全表。程序没有自动公开发布或向社区回流的步骤。协议与数学实现独立编写，未直接移植上游GPL捕获源码。

## 许可证

hash-slinging-slasher在Cargo元数据声明GPL-3.0-or-later，Cordycep仓库提供GPLv3全文。直接复制或修改上游捕获实现需按适用GPL条件处理，不能只改名称后塞进现有引擎。独立EXE也并非天然免除其源码/许可分发要求；若日后再分发，应明确组件边界、包含许可证并提供对应源码，单独审核实际分发组合。[上游Cargo许可证](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/10108fa4c54509989143e8c8028c7a76ab57d28a/Cargo.toml)、[Cordycep许可证](https://github.com/Scobalula/Cordycep/blob/3be1e21221c61f3f021346996f4b17586e18ad4d/LICENSE.md)
