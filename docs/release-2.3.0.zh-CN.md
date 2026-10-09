# 2.3.0 上游更新适配

日期：2026-10-09。许可证：MIT。最终验证报告随发行附件提供。

本版保留Avalonia NativeAOT液态玻璃界面与内置Python后端，一键操作仍为“输入 → 估算 → 确认计算 → CSV／CDB导出”。普通电脑无需安装Python、.NET、Git或原研究项目。教程随EXE安装包提供，界面按钮及F1可一键打开。

发行附件为Windows x64 EXE安装包、对应源码、SHA256文件和最终验证清单；统一在[2.3.0发布页](https://github.com/ez4cywa/cod-name-finder/releases/tag/v2.3.0)提供。安装器及运行环境的实际验收状态以本版验证清单为准。

## 本版改进

- 根据hash-slinging-slasher固定main提交`dbe25197cee05b8315b4effff1841ed4868152f0`，增加MWII、MWIII、BO6、BO7、COD2026现代CODIDS v1离线导入；强制同名`.pools.txt`，按清单type识别，拒绝错用实时池号。
- 声音alias的63位旧快照不会被提升为现代满64位正式目标；不完整域保持只读线索边界。
- 音频表显示路径通过原source-table键的完整回算恢复后才成为可信种子。无键文本和外作名称只作候选，当前目标惯例必须同类型、同profile且完整键验证。
- 新增重复namespace同步替换、当前alias缺失声音文件族探索，以及编码尾前的末ASCII字节反求；codec、take与目录来自真实目标观测。
- 增加型别明确的动画到alias、武器槽到图片／材质有限推测。新规则沿用关联名称推测开关和总候选预算，Saluki现有键／原样名称继续排除。
- 两条新声音计划最多100万候选／128计划，双方可用时为namespace预留至多四分之一候选及计划额度，未用额可返回alias，避免大alias语料饿死namespace探索。
- 末字节先按profile归一化合并等价前缀；字节运算与桶探测合计限800万工作单位／8万前缀／1万候选，报告保留实际准备工作和省略范围。

上述规则参考[PR #2464](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2464)、[#2465](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2465)、[#2466](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2466)的问题结构，本地独立实现，GPL源码未复制。另向上游提交声音take解析修正[PR #2467](https://github.com/KingslayerKyle/hash-slinging-slasher/pull/2467)；开放或合并状态以该PR为准。

## 验证记录

已对固定上游提交的五份公开快照实际只读验证，共9,513,578条原始记录、340,229个动画目标。逐作品检查原始记录保留、池清单type映射、动画筛选及63位alias拒绝full64认证；数量是输入范围，不是新增名称数。

本版Python回归、NativeAOT、EXE安装器及新增规则的最终逐项结果集中提供于发行附件[CODNameFinder-2.3.0-validation.json](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.3.0/CODNameFinder-2.3.0-validation.json)。清单区分合成验证、公开快照只读导入和实际加载器现场结果，不把预检当作最终安装通过。历史2.2.2的524项测试及安装验收保存在[历史发行说明](release-2.2.2.zh-CN.md)，不代替2.3.0的验收，也不把上游吞吐写作本机新规则成绩。

源码完整回归已通过741项Python测试，注册表生成`--check`和变更格式检查通过。声音计划包含57项测试，pipeline新规则集成包含20项；压力用例验证namespace预算预留、剩余额度回流及原候选消费无重复。安装器和NativeAOT的实际通过范围读取上述同版本最终清单。

详细输入、实现、限制和可重验路径见[2026-10-09更新记录](upstream-update-20261009.zh-CN.md)。本地验证原始数据、整份公共资产快照、用户索引、授权文件和游戏媒体不随公开源码或发行附件提供。

## 使用与边界

升级后保留完整安装目录。导出文件夹按原流程运行；现代`.ids`与同名`.pools.txt`一起复制，选择实际作品与相符资源域。已有完整JSON快照可继续使用。默认保留关联名称推测；首次关键词留空、CPU、完整键、社区同步关闭，先跑附带示例。

预算耗尽或停止时保存已经完成批次和已验证结果，有限计划完成不代表所有名称可逆。现代公开快照导入不表示本地五作品现场捕获均已适配；现场捕获仍核对具体加载器、配置、模块及布局。2026-10-05的MW7 Beta现场记录保留，BO7现场捕获尚未通过对应验收。

Saluki输出必须独立回读并保留旧索引合并关系；Saluki GUI现场加载、第二台物理电脑和八小时持续运行尚未据本版新规则完成验证。
