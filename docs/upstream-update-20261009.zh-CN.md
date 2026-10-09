# 2.3.0：2026-10-09上游更新适配记录

本次根据用户指定的 hash-slinging-slasher 开放PR列表核对最新实现，参考`main`固定提交为 [dbe25197cee05b8315b4effff1841ed4868152f0](https://github.com/KingslayerKyle/hash-slinging-slasher/commit/dbe25197cee05b8315b4effff1841ed4868152f0)。本地版本为2.3.0，最终验证报告随发行附件提供。原有一键GUI、NativeAOT前端、内置Python后端、可选GPU及Saluki增量导出流程保留。

本文件记录可追溯的输入事实、实现和验证边界。上游GPL源码没有复制到本地MIT应用；声音计划、模逆计算和严格快照读入为独立实现。社区整表、游戏媒体、加载器和公开整份资产快照不随本地安装器分发。

## 本次核对哪些更新

| 来源 | 更新主题 | 本地落点 |
|---|---|---|
| [PR #2464](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2464) | `mw4-sound-byte-before-encoding`：目标已观察编码尾与源表已验证basename前缀，反求最后ASCII字节 | `finder/soundbyte.py`，有限准备预算与完整键重新验证 |
| [PR #2465](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2465) | `mw4-linked-sound-namespaces`：目录／basename重复命名段关联替换 | `finder/soundplans.py` 的`repeated-namespace` |
| [PR #2466](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2466) | `mw4-target-alias-file-paths`：当前alias缺失声音文件族，借最深公共词段下的实际目录、take及codec | `finder/soundplans.py` 的`alias-missing-family` |
| [最新main的快照目录](https://github.com/KingslayerKyle/hash-slinging-slasher/tree/dbe25197cee05b8315b4effff1841ed4868152f0/snapshots) | 现代五作品CODIDS v1与捕获池类型清单 | `finder/snapshot.py`：强制相邻清单，以捕获type识别，保留位宽边界 |
| [上游修正PR #2467](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2467) | `fix sound take family gaps hidden by encoding-tail digits`：先隔离点尾，再解析声音take | 已提交上游的独立修正；本地规则保留原take与完整编码尾 |

PR #2467记录时为开放状态。本地修正测试及文档检查通过；上游首次fork的CI处于`action_required`，等待维护者授权，不能写成上游CI已通过或已合并。PR实时状态以链接为准。

## 导入现代快照时保持捕获本身的类型

现代五作品为MWII、MWIII、BO6、BO7、COD2026。CODIDS v1每条数据虽然占用uint64字段，但已清除最高位，实际只存63位。现代输入必须同时提供同名`.pools.txt`，核对作品、总数、各池计数和原始记录排序。

捕获清单中的池号是该份离线数据的位置。合并、追加声音／alias等处理会使它与本机实时加载器的pool index不同。因此本地以清单type名识别`xanim`、`sound_asset`等受支持类型，不借用本地40字节池结构的数字索引。未知type保留原始记录、排除正式计算；模型目标继续排除。

资源类按已经有证据的作品域使用`iw-resource63`。`sound_alias`被明确识别为声音alias，但现代该域需要Treyarch满64位。失去最高位的63位记录不能提升为full64目标，即使低63位命中也不能直接导出。可信alias名称可用于推测声音文件；正式alias认证仍要求另有当前完整64位目标。

BO4／BOCW旧输入保留其独立登记的作品池映射，不将现代type解析方式反套到历史格式。本地增强JSON则继续保留raw64、逐池profile、build与文件SHA证据，`complete`仅表示当前已加载集合的已适配范围稳定，不表示全游戏。

## 先验证种子，再学习当前目标惯例

音频社区表可能把内部点尾显示成路径，例如`.lnn.75.48000.all`显示为`/lnn/75/48000/all`。`resolve_table_spelling()`根据少数明确结构尝试恢复，只有恢复后的拼写命中原表完整键及该表规则，才成为源验证种子。BO4反斜杠、现代折叠斜杠及不同表掩码仍各自处理。

没有回算成功的显示名、普通TXT、文件名和跨作品词典仅能提供候选。源表验证也只证明源种子：若要作为当前作品的目标模板，还必须命中当前目标的同资产类型、同profile完整键。名字相似、资产类型相似、低63位一致都不能替代这项判断。

目标模板按类型组织，避免将动画当作alias、把声音文件当作声音库，或让外作名称改变当前作品的“已有文件族”统计。`finder/typedplans.py`进一步独立表达动画到alias、武器槽到图片／材质的有限关系，输出继续是候选计划。

## 三项声音探索如何工作

### 重复命名空间关联替换

namespace是完整目录component，同时在文件名stem中按整词出现，总计至少两次。重叠的短namespace让位于最长匹配；同一namespace在目录和文件名中的所有出现同时替换，防止产生目录写武器A、文件名写武器B的拆散组合。

替换namespace和编码尾从当前已经验证的声音一起学习。供体只提供候选形状，保留其原始正／反斜杠。相同形状的多份供体先合并，避免为同一目标候选重复花预算。

### 从当前alias探索缺失声音文件族

文件族取underscore名称stem，去掉可选末尾数字take及`_ads`。只有至少3个词段的当前alias族、且当前目标声音尚未持有该族时，才寻找最深共同词段前缀。相应目标声音提供原始目录与完整“take＋编码尾”元组。

例如`wpn_plr_ar_alpha_reload`可以借`wpn_plr_ar_alpha_fire_001.qnn.85.48000.all`的目录和`_001.qnn.85.48000.all`。`001`的宽度保留，不能把另一观察的take与这个编码尾拆成任意笛卡尔积。外作donor存在reload族不代表当前作品存在，因此不会遮挡本作缺失族。

两类计划总上限100万候选、128条计划。别名缺失族先跑；双方有潜在规则时，为namespace预留至多四分之一的候选和计划额度，默认可留32条namespace计划机会。只有一种方法时使用完整额度；namespace未用的额度可还给alias，同一部分文件族从已消费游标接续，不重复已发候选。只有1条计划等极小预算仍确定优先alias，不承诺两法都跑。

长名称按1024 UTF-8字节界限修剪，不存在合适观测就不发计划。alias与观察元组保持短列表，生成前不会物化巨大的全积。报告给出分规则实际发出量、namespace预留额及整体省略上界，不把它们当作去重后的新名称数量。

### 编码尾前的末字节反求

FNV奇数乘数在`2^63`／`2^64`模环中可逆。本地在相应完整比较域剥离目标已观察到的编码尾，反求basename的最后一个可打印ASCII字节；低63位环封闭，不假装知道被清除的高位，也不需要猜测完整状态的两个lift。

源前缀只来自通过原表键验证的拼写，尾只来自当前声音目标。该步骤不枚举任意目录、全字符句子、codec或采样率；低60位初筛和不相符算法跳过。前缀先按profile归一化合并等价拼写，避免大小写或斜杠等价造成桶内重复工作。准备的字节运算与桶探测合计限800万工作单位、8万个前缀及1万条输出候选，桶内循环也检查预算与停止；报告记录归一化去重、探测次数、实际准备工作及未处理范围。所有输出仍进入普通计划扫描、独立完整键回算、冲突处理和Saluki排除。

## 一键流程和预算

新规则受原有`cross_asset`关联名称推测开关控制，界面文案为“根据已知名称推测关联资产”，支持类型同步包含alias、图片和材质。软件仍按输入、估算、确认计算和导出操作；没有新增必需页面、后台服务或研究项目依赖。教程随完整EXE安装负载提供，界面按钮及F1均可打开。

原有跨资产规则800万组合／512计划上限保留；新声音规则和末字节准备分别设置上限，全部继续受本次总候选预算与时间约束。暂停、停止并保存、方法指纹和缓存复核保持生效。正式CSV／CDB只含独立验证且不在所选Saluki索引已有键或原样名称中的新增项。

## 实际输入验证与结果边界

2026-10-09对固定上游提交的五份公开快照进行了只读解析、工作库导入、原始记录保留、动画类型筛选和alias full64拒绝检查：

| 快照 | 作品 | 原始记录 | xanim目标 |
|---|---|---:|---:|
| `modwar22.ids` | MWII | 1,594,748 | 55,778 |
| `yamyamok.ids` | MWIII | 1,915,075 | 64,407 |
| `blackop6.ids` | BO6 | 2,075,902 | 87,620 |
| `blackop7.ids` | BO7 | 3,438,755 | 97,260 |
| `modwar7.ids` | COD2026 | 489,098 | 35,164 |
| 合计 | 5作品 | 9,513,578 | 340,229 |

本地证据文件为`validation/modern-upstream-ids-20261009.json`，记录源提交、逐文件SHA、实际type映射、保留数量和拒绝结果。`validation`是工作验证输出，不要求公开分发原始快照或私人名称结果。

这些数量证明读入和类型约束实际通过，不能表示已经找到了相同数量的名称、已穷举全部候选、现代五作现场捕获全部可用或全游戏完整。最终Python、NativeAOT、安装器及输出验证结果由[2.3.0发布说明](release-2.3.0.zh-CN.md)集中记录。2026-10-05的2.2.2现场捕获与吞吐属于历史结果，不沿用为本版新规则的速度测量。

本版完整源码回归通过741项Python测试，包含57项声音计划和20项pipeline集成测试；注册表生成一致性及变更格式检查通过。声音压力用例确认默认128条计划可分配96条alias与32条namespace机会，候选预算8时可分配6条alias候选与2条namespace候选，未用预留转让时没有重复消费。最终安装EXE、NativeAOT自检和其他逐项验收以同版本[validation.json发行附件](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.3.0/CODNameFinder-2.3.0-validation.json)记录为准，不把源码单元测试等同于安装包已通过所有验收。

## 证据到实现的对应关系

| 证据 | 结论 | 实现与重验路径 |
|---|---|---|
| 固定main的现代CODIDS及相邻池清单、五份实际导入报告 | 离线池号与实时池号不同；位宽只有63 | `finder/snapshot.py`、`tests/test_snapshot_modern_upstream.py` |
| 原表hash／显示名及独立参考测试向量 | 恢复拼写必须命中原source-table键 | `finder/spellings.py`、`tests/test_spellings.py` |
| PR2465／2466的关系与本地自建名称 | 同步namespace及目标缺失族可以构造输入未出现的候选 | `finder/soundplans.py`、`tests/test_soundplans.py` |
| 公开FNV模逆关系与PR2464的有限末字节问题 | 相符模环可直接反求末ASCII字节，必须设置准备预算 | `finder/soundbyte.py`及对应测试 |
| 型别明确的已回算输入和当前同类型模板 | 跨类型词法关系不能代替目标本域验证 | `finder/typedplans.py`及pipeline集成测试 |

开发者在仓库根执行`python -m pytest -q`重跑测试，完整构建和安装器验收步骤见[构建指南](building.zh-CN.md)。独立CDB回读不替代Saluki GUI现场加载；公开快照兼容不替代本地加载器build适配。
