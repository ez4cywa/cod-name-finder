# 本地新版 Cordycep 适配核验

调查日期：2026-10-05，目录：`D:\_tiqu\Cordycep`。本页比较软件 2.2.0 已登记的加载器与用户刚更新的本地加载器，不推定其它发行版等价。游戏、授权及加载器二进制均不随本软件分发。

**新版 CLI 的 COD2026 Beta 接入已通过真实 BAT 启动、独立只读内存核验和捕获验证。**本次 common files 加载集合生成 337,958 个原始 key 条目和 43,105 条候选字符串；完成状态只代表已映射的当前加载范围。BO7 正式版尚未完成真实捕获验证。

## 本次实际变化

新版 `Cordycep.CLI.exe` 仍报告文件版本与产品版本 **2.9.0.0**，但文件内容不同。仅依赖版本号会把两个 build 混为一谈，因此适配绑定可执行文件 SHA256，并同时绑定对应作品的配置和游戏转储 SHA256。

| 文件 | 大小 / 版本 | SHA256 |
|---|---|---|
| 原已核验 CLI | 18,040,832 字节 / 2.9.0.0 | `fe43506a599fd84472c81599ace976b6ee6cde8b545745ea7ff0e3046fe1e1e7` |
| 当前 CLI | 18,057,728 字节 / 2.9.0.0 | `a3a700bd4080f1d3eb7ee7084e0f42abc597c33f5a6eeded154105239f43b6f9` |
| 当前 GUI `Cordycep.exe` | 14,862,848 字节 / 2.8.3 | `8324f874307865b2d0add84ab37197342d951fd54ae3929d45625d5f76d6d51a` |

当前 CLI 修改时间为 **2026-10-05 18:04:36 +08:00**。GUI 可执行文件与 CLI 的产品版本不同，本次 CLI 适配结论不自动扩展到 GUI 文件。

两个作品的配置和转储均未变：

| 作品 | 绑定文件 | SHA256 |
|---|---|---|
| COD2026 Beta | `Data/Configs/CoDMW7HandlerBeta.toml` | `3456739384d434ce14e0f77f044c6539959bf6f98737bfdd5c04899f85530f31` |
| COD2026 Beta | `Data/Dumps/cod26-cod_dump.exe` | `428309e60147007e26a86b329fea6703ebd0bce6937aa6c5fa17fda4ed89f7b5` |
| BO7 正式 | `Data/Configs/CoDBO7Handler.toml` | `2243f645db9804ec2ab8f1a7cd4ab1872a8d122af207945e823343845665883a` |
| BO7 正式 | `Data/Dumps/cod_dump.exe` | `6ccc9ef5af213d9047f64a5a1212d06047ecc008eeb56f17ef6841511ff1fc4a` |

`RunMW7Beta.bat` 与 `RunBO7.bat` 的原有启动参数未变，分别使用 `mw7` 加 `beta` 标志和正式 `bo7` handler。

## 状态文件与类型表

初始 `CurrentHandler.json` 记录 PID **41384**、`MODWAR7`、`beta` 和 COD2026 Beta 转储路径。调查进行时该 PID 已退出，系统再次枚举没有 Cordycep 进程。只读 `OpenProcess` 返回 Windows 错误 87；因此这份 JSON 在当时属于过期实例状态，不能据其地址读取任意新进程。

该实例留下的 CSI 文件为 **87 字节**。独立解析完整消费全部字节，其游戏 ID、池地址、字符串地址、UTF-8 游戏目录、flags 均与 JSON 相符。尾部仍是目录及 flags 扩展，不是字符串池大小指针。

重新从未变化的游戏 PE 文件静态读取类型名指针表：

| 作品 | 类型名表 RVA | 项数 | 已映射池复核 |
|---|---|---|---|
| COD2026 Beta | `0xc8018a0` | 414 | 16 / 16 相符 |
| BO7 正式 | `0xb2c5a10` | 408 | 16 / 16 相符 |

两个表均保持：6 xanim、10 material、14 image、26 soundbank、27 soundbanktransient、55 localize、56 attachment、57 weapon、63 rawfile、64 gscobj、65 gscgdb、66 stringtable、87 animpkg、110 scriptbundle、116 keyvaluepairs、186 sndasset。7 为 xmodelsurfs、8 为 xmodel，继续排除模型。嵌套名称域和其它未知池仍不分配推测算法。

新版实际实例的运行验证确认 **512 个 40 字节池记录、96 字节节点前缀**，与原布局一致。每次读取仍须核对 PID、路径、状态新鲜度、节点 kind、链表指针及前后状态，并在已映射范围稳定后才声明该范围的快照完成。

## 新版现场验证结果

集成验证实际执行所选 `RunMW7Beta.bat`，识别到所属加载器 PID **15240**，并通过本次 Job 的进程列表核对归属。该会话在验证完成后已关闭。PID 和地址只记录本次证据，不能复用于后续运行。

独立只读检查得到：

- JSON 与 87 字节 CSI 的游戏、地址、目录和 flags 完全匹配；读取前后状态稳定。
- 当前映像类型名表的 **414 项**与静态 PE 表逐项相符；采用换行并保留最后一个换行的 SHA256 为 `aa403e9fc2d6d2f0dc3b4d06a2134e6f73e417ccac1677be29a984b6d2f2b345`，与既有登记一致。
- 已映射范围包含 **16 个非模型池**。pool 65 在当前 common 加载集合为空；其它已映射池的哨兵、首个有效节点和 node.kind 均符合布局。模型池 7 / 8 的结构仅用于独立证据核验，实际快照继续排除模型。
- 字符串池实际使用长度为 **1,625,161 字节**，可读保留区域为 **33,558,528 字节**；捕获使用实际长度作为边界。
- 实际快照保留 **337,958 个原始 key 条目**，提取 **43,105 条候选字符串**，已映射非模型池两次读取一致，返回 `status=completed / complete=true`。未知池 key 仅作诊断，不参加名称计算。

加载与验证流程实测为 **10.84 秒**，这是本机本次记录，不能作为其它电脑的固定耗时。`RunMW7Beta.bat` 使用 `loadcommonfiles`；此次数量不代表全游戏资产总量，也不证明已经执行 `loadall`。

BO7 实际尝试 `RunBO7.bat` 后，**6.85 秒**内未形成可核对的完成提示，没有生成完整捕获。错误为“Cordycep 没有返回可核对的完成提示”，原因尚未确定。该会话已关闭；不能将 COD2026 的成功等同于 BO7 运行验证成功。

## 适配登记方式

`finder/cordycep_profiles.json` 保留原 `version=1`、`loader`、作品与池映射，以兼容已经生成的离线快照。新增 `layout.id=cordycep-pool40-node96-v1`、`preferred_loader_sha256` 与 `loader_builds`。

每个 `loader_builds` 项独立记录文件名、版本、SHA256、布局适配器以及对应作品的配置 / 转储指纹。新 CLI 为首选，原 CLI 仍可处理既有环境。未知 CLI 内容、错误的作品配置或不同游戏转储均不套用本次枚举。

新 build 的 COD2026 条目现已标为 **`runtime_verified`**。BO7 保持 **`static_pending_runtime`**，避免把配置文件存在等同于正式作品成功加载。

静态调查仅读取普通可执行文件、配置、状态文件及类型表；后续集成验证仅控制软件自己启动的加载器实例，没有按名称停止用户的其它进程。两阶段均没有读取 `License.ccl`、`__h2Exe` 或任何授权内容。

静态证据为 `validation/cordycep-latest-static.json`；独立运行检查为 `validation/cordycep-latest-readonly.json`；真实 COD2026 和 BO7 尝试分别为 `validation/cordycep-latest-live-cod2026.json`、`validation/cordycep-latest-live-bo7.json`。原布局、类型表来源和首次捕获证据见 [本地 Cordycep 捕获接入核验](cordycep-local-research.zh-CN.md)。

## 真实 BAT 启动的归属边界

新增 `finder/batch_loader.py` 负责执行用户选定的本地 BAT。脚本必须位于所选 Cordycep 目录根目录，允许中文和空格路径；不替换用户脚本中的多行流程。脚本路径含 `%` 或 `!` 时会明确拒绝，避免 CMD 路径展开歧义。

启动使用系统目录中的绝对 `cmd.exe`，不信任工作目录中的同名程序；禁用 CMD AutoRun，隐藏窗口。首先以挂起线程创建 CMD，并给它的标准输入、合并标准输出 / 错误建立指定的继承句柄列表。CMD 加入只属于本次操作的 Windows Job 后才恢复线程，因此不会先运行脚本再尝试判断后代归属。

Job 设置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，不设置 breakaway 标志。本次结束时关闭自身 Job，Windows 会终止所属进程；未按进程名批量停止其它实例。Job 创建或分配失败时，挂起的新 CMD 被清理且脚本未执行，整个启动报错，不退回缺少归属约束的启动方式。[Windows Job 契约](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[挂起进程分配规则](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)

BAT 使用 `start` 时，CMD 根进程可能先返回；所属加载器仍须从实际状态文件识别 PID，并用 `owns(pid)` 查询本 Job 当前进程列表。不能把 CMD PID 当作 Cordycep PID，也不能仅因同目录内出现加载器就认定它由本次操作启动。

`tests/test_batch_loader.py` 的 **6 项普通 Windows BAT / Python 测试通过**，覆盖中文空格路径、多行回显、退出码、交互输入、嵌套后代归属、只关闭自身进程树、归属分配失败不执行脚本，以及 CMD 退出后的 `start /B` 子进程仍被 Job 管理。真实 Cordycep 验证另按上节所述记录，两个测试范围分别保留证据。
