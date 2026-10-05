# 上游 hash-slinging-slasher 原理、MW2022–COD2026 适用性评估与本地改进方案

日期：2026-10-05。上游版本：KingslayerKyle/hash-slinging-slasher `main`（4,911 提交，GPL-3.0-or-later）。
本文只采用仓库源码、仓库维护者文档与 cod-name-db 事实，未运行上游二进制；结论为本地 CODNameFinder 2.0.1 的改进设计依据。COD2026 的资产/声音域算法为 2026-10-05 实测实证（§3.0），其脚本/dvar/omnvar 域仍未证实。

## 1. 结论摘要

- **上游方法与具体游戏解耦，原理上可覆盖 MW2022 至 COD2026 的全部作品**：它的三步（捕获 id 集合 → 种子重组候选 → FNV 命中判定并排除已发布）只依赖「哈希函数 + 目标 id 集合 + 排除表」三件与游戏弱耦合的输入。真正绑定游戏的只有这三件事的**数据**，而非代码。
- **但上游自身只提交了 BO4 与 BOCW 两个快照**（`snapshots/` 仅 `blkops04.*`、`blkopscw.*`）。扩展到新时期每一作都需要：a) 用自己的游戏副本重新执行一次捕获（Cordycep + Windows + 游戏，feature `cordycep`，默认关闭）；b) 按目标表选择 offset 与掩码（IW 时代 `_v2` 表用 IW offset）；c) 按该作重建命名惯例词表（verbatim 跨作移植是实测死路，respelling 有效）。
- **COD2026（MW4）算法大部分已实证，无需反编译**：用 cod-name-db 的「已知名称→已知哈希」样本做表考古，对全部 40 张表逐行试算——`rex_` 前缀族（5,663 行）与 `rex/` 声音路径族（22,813 行，回算率 100%）**全部命中 `FNV-1a(IW offset 0x47F5817A5EF961BA) & 63 位`**，即本地 `iw-resource63`：资产名、animpkg、声音库、声音文件四域通吃；声音银行别名则按表级规则用 Treyarch offset 满 64 位（373/373）。方法、逐表明细、副产品（strings 60 位、SAB 的 SDBM）与一个重要边界（同一张表内不是所有行都能回算，导入须逐行校验）见 §3.0。**仍未证实的只剩 COD2026 的脚本/dvar/omnvar 域**，门控保持不变。
- **本地项目与上游的差距不在算力，而在架构**：上游用实测证明后缀经反向剥离后近免费（候选询问量/实际哈希数 = 218×），GPU 不是当前瓶颈（内存访问受限 + Python 生成器受限）。本地已有 OpenCL 内核且设计正确（设备侧拼串、只回传命中位图），但缺少剥离引擎、方法账本/指纹、幂等扫掠、社群表同步与预算预估层。

## 2. hash-slinging-slasher 工作原理

### 2.1 三段式架构（来源：README.md、AGENTS.md、docs/HASHES.md）

1. **捕获（capture）**：用 Cordycep 不加游戏地加载 fast file，把每个 pool 的 asset id 写成 `snapshots/*.ids`，再用 `*.pools.txt` 记录每个 pool 的索引、资产类型与数量。这一步需要游戏、Cordycep 与 Windows，**每作一次性**；BO4/BOCW 已停更，快照即终态，不再过期。上游只提交了这两个游戏的快照。
2. **破解（grind）**：不需要游戏。候选 = 已证实名称的重组；哈希 = FNV-1a 64 位（Treyarch offset `0xCBF29CE484222325`，prime `0x100000001B3`），名称先小写化并把反斜杠折叠为正斜杠；asset id 按 **63 位**比较（引擎用最高位作标志）。命中即证明游戏自身引用该名称；再排除 cod-name-db 已发布名称，剩下才是新发现。
3. **回流（submit）**：PR 提交到 cod-name-db；每次运行带指纹摘要防重复劳动；连续三次零产出的方法被 `src/futility.rs` 拒绝启动。

### 2.2 关键机制（值得本地借鉴的核心）

- **反向剥离引擎**。prime 为奇数，模 2^64 存在逆元，`h = (h * prime_inverse) ^ byte` 可精确剥掉一个字节。于是「后缀」不必乘到每个候选上，而是从每个目标 id 上剥一次：成本从 `stems × begins × ends` 的**乘积**变成**求和**。实测：一次通用 pass 询问 41.72 T 候选，只实际计算 191.2 G 前向哈希（来源：docs/GPU.md）。`final_byte`（剥最后一个字符）达到每 18 个候选出 1 个名字，是全场最高效方法（METHODS.md）。
- **种子原则**。候选只从真实名称重组：已发布表、已确认名、dump 出的字符串。实测名字中位数 7–9 个下划线分段，词组序列空间先于名字超过 2^63，**字典造句结构性无效**（README/AGENTS.md §6、GPU.md）。
- **方法即脚本**。Python 生成器打 name 到 stdout，管道给 `confirm_list`；cross product 写 plan 文件交给 Rust 引擎展开。方法库（scripts/）+ 侦察脚本（coverage/seams/reach/methods_report）+ 提交记录（submissions/）构成可持续复用的知识库。METHODS.md 记录 104 个已跑方法与各自「reach 什么、何时耗尽」。
- **声音独立 pass**：声音名的形状（深路径、点尾、BO4 反斜杠）与模型完全不同，共享一次运行两边都变差；BO4 声音名保留反斜杠，须 `--no-fold`，否则「看起来健康地匹配 0 个」（README §How it works、AGENTS.md §5）。
- **指纹防重**：每次运行的方法/游戏/pool/旗标/词表摘要进入提交，重复即拒绝（AGENTS.md §8）。本地磁盘数据不计入指纹（否则同一方法人人指纹不同，guard 永不触发）。
- **GPU 实测结论**（docs/GPU.md，Ryzen 7 7800X3D + RX 7900 XT，2026-08-19）：通用搜索 3.94×10¹⁰ equivalent candidates/s，实际前向哈希 1.81×10⁸/s，差 218 倍——差距全部来自剥离架构。每个候选约 400 cycles，其中 ~340 是过滤器探测（128 MB 位图超出 L3），属**内存受限**。参考 GPU 工具：acts OpenCL 每候选写 8 字节进 64 MiB 缓冲再 PCIe 回传 host 扫描，上限 ~10⁹ candidates/s；codehash 反向模式因 ~100 MB 表探针降到 1.11×10⁶ stems/s。结论顺序：先修 I/O（`BufRead::lines` → bytes 读取，12× 提速）、再提速生成器（Python 管道 7.7×10⁵/s，确认器空闲 99%）、再缩目标集，最后才考虑 GPU。**任何 GPU 提议的名字必须在 CPU 复核**（codehash 曾因索引溢出 8 bit 报错 355/8125 个名字）。

### 2.3 许可

GPL-3.0-or-later。注意：FNV 可逆性是标准数学，抄袭其数学结论不构成衍生；若直接复用 `src/search.rs` 代码则受 GPL 约束，本地应以「自研实现 + 参考算法」方式落地（与 docs/github-research.md §4 对 porter-lib 的处理一致）。

## 3. 能否用于 MW2022 → COD2026？

「MW2022」= Modern Warfare II（2022），至「COD2026」之间：MWIII（2023）、BO6（2024）、BO7（2025）、COD2026/MW4（2026）。

### 3.0 COD2026 算法实证：rex 表考古（2026-10-05 实测，覆盖全部 40 张表）

方法：cod-name-db 的 CSV 为「hex_u64 键,名称」无表头格式（docs/github-research.md §1）。已知名称即可反推算法——对每张表中含 `rex` 子串的每一行，试算全部候选 profile（FNV-1a 64 的 IW/Treyarch 两 offset × 63/64/60 位掩码、FNV-1a 32、SDBM 32），匹配率与命名形状一致即锁定。当日 `csv/` 共 40 表，25 表含 `rex`，合计约 30.5K 行，全部结果如下。

| 表（域/表级规则） | rex 行 | 命名形状 | 验证结果 |
|---|---|---|---|
| `fnv1a_xanims_v2`（IW 资产） | 5,169 | 5,104 `rex_` 前缀 + 65 子串 | **iw63 5,169/5,169（100%）** |
| `fnv1a_ximages_v2` | 1,066 | 33 前缀 + 1,004 子串（`barext` 等） | **iw63 1,066/1,066（100%）** |
| `fnv1a_xmaterials_v2` | 778 | 763 子串 | **iw63 778/778（100%）** |
| `fnv1a_animpkgs_v2` | 526 | 526 前缀 | **iw63 526/526（100%）** |
| `fnv1a_xsounds_v2`（IW 声音文件） | 23,734 | 22,712 嵌入 | 见下方分组分析 |
| `fnv1a_soundbanks_v2`（声音库） | 185 | 185 嵌入（`weapon_rex_ar_akilo_npc.all`） | **iw63 185/185（100%）** |
| `fnv1a_soundbanks_aliases_v2`（别名，Treyarch offset） | 373 | 373 嵌入（`wfoly_rex_plr_ar_kilo2_inspect_empty_07`） | **trey64 373/373（100%，满 64 位无掩码）** |
| `fnv1a_strings`（BOCW 60 位表） | 7 | 巧合子串（`coverexposed` 等） | trey60 7/7——**再次证实该表 60 位规则** |
| `fnv1a_xmodels`/`xmaterials`/`ximages`（非 v2，Treyarch 表） | 56/39/35 | 多为巧合子串（网格哈希尾、`horex`、`containerexterior`） | trey63 31/56、35/39、22/35；未中者为社区重建显示名 |
| `bo2_sab` | 11 | BO2 声音路径（`t_rex_fence`，保留反斜杠） | **sdbm32 11/11（小写、保留反斜杠）** |
| `bo2_ipak` | 10 | — | 0（native 键非名称哈希，符合 HASHES.md） |
| 12 语言 xsounds + `soundbanks_aliases`（非 v2） | 各 1–2 | 巧合（`ourexfil`、`tmrexp`） | trey63 命中 |

形状定义：`rex_prefix`=名称以 `rex_` 开头（MW4 内容：武器代号 kilo2/akilo/bmike3/sierrax、`rex_preorder_keyart_*`）；`rex_embedded`=`rex_` 在中段；`rex_substring`=形似巧合（`forexfil`、`barext`、`coverexposed`、`horex`、网格尾）。

**xsounds_v2 分组分析（关键，决定声音域结论的可信边界）**：按名字首路径段分组实测，本表**不是单一哈希来源的表**：

| 路径组 | 行数 | iw63 命中率 |
|---|---|---|
| `rex/`（MW4 声音文件根） | 22,813 | **100.0%** |
| `t10/`（BO6 声音） | 21,054 | 99.8% |
| `sat/`（BO7 声音） | 14,634 | 99.9% |
| `jup/`、`core/`、`iw9/`、`s6/`、`vo_efforts/`、`gen_music/`（表内全部行，非 rex 子集） | ~41.2 万 | 3%–32%，**且 Treyarch offset（60/63/64 位）、FNV32、SDBM32 与 7 种名字变换全部 0 命中** |
| `iw9/amb/rex_emitters*` | 703 | **0%**，同上无任何变换/profile 命中 |

即：可回算的家族（rex/t10/sat）全部是 iw_resource63；不可回算的是老路径组与 `rex_emitters`——这正是上游 HASHES.md 明示的"表中许多行是社区重建显示名，无法回算"，703 行 rex_emitters 属同一现象而非新算法（已用剥尾/换缀/去前缀等 7 种变换 × 双 offset 验证）。**设计含义：cod-name-db 表格只能按行回算后使用——回算中的行进语料/排除集，回算不中的行仅作候选词汇，不得当作已验证名称。**

**结论（分域）：**

- **COD2026 资产名 / animpkg / 声音库 / 声音文件 = `iw-resource63`**（IW offset，63 位掩码），与 MWII/MWIII/BO6/BO7 同算法——本地既有 profile 直接可用，无需新增算法。
- **COD2026 声音银行别名沿用表级规则：Treyarch offset，满 64 位无掩码**（373 行全中，与 HASHES.md 对 `aliases_v2` 的规定一致）。
- 未证实域收缩为：脚本字段、dvar、omnvar（BO6/BO7 的 t10 系待样本确认）。
- 副产品：Treyarch 非 v2 表与 `bo2_sab`/`strings` 的巧合行全部按各自预期 profile 命中，独立复核了 HASHES.md 的掩码规则（strings 60 位、aliases 满 64、SAB 用 SDBM 而非 FNV32/DJB2）。

### 3.1 逐作证据矩阵

| 作品 | 资产/资源名哈希 | cod-name-db 表（docs/HASHES.md） | 上游快照 | 判定 |
|---|---|---|---|---|
| MWII (2022) | IW offset FNV-1a 63 位（`iw_resource63`） | ximages_v2、xmaterials_v2、xsounds_v2、soundbanks_v2、animpkgs_v2、bones(FNV-1a **32** 位满宽)、aliases_v2(Treyarch offset，**64 位无掩码**) | 无 | 方法适用；需自捕获或用户导出 |
| MWIII (2023) | 同上 | 全 v2 表（含 xanims_v2） | 无 | 同上；bones32 |
| BO6 (2024) | 资产 iw_resource63；脚本 `iw9_script64`（本地实测坑：HashIndex 文档写 63 位、源码返 64 位，须保 full64/stored63 两 profile）；dvar `iw_dvar64`；omnvar `t10_omnvar64`；战役 `t10_sp_script64` | 全 v2 表 | 无 | 适用；**域最多**，逐域选 profile |
| BO7 (2025) | 资产同 BO6；sat16 VM 同时注册 #/@/%/t/s/o 多个域（docs/hash-algorithm-coverage.md） | 全 v2 表 | 无 | 适用；禁止混用单一「BO7哈希」 |
| COD2026 (2026) | **iw_resource63（rex 表考古实证：资产名/animpkg/声音库/声音文件 + 别名 trey64，§3.0）**；脚本/dvar/omnvar 未证实 | 无独立表；MW4 内容以 `rex` 混入 `_v2` 表 | 无 | 资产+声音域可启用；脚本域保持门控 |

证据来源：上游 docs/HASHES.md（file→game→hash→mask 全表）、本地 docs/hash-algorithm-coverage.md（逐作 handler 引用与 atian-cod-tools 源码核对）。

### 3.2 落地到新时期的四个硬约束

1. **掩码逐表不同，不是每游戏统一**。asset 表 63 位；`fnv1a_soundbanks_aliases_v2.csv` 与 `bones_v2` 是 Treyarch offset **满 64 位无掩码**；`fnv1a_bones.csv` 又是 FNV-1a **32 位**。掩码搞错不会报错，只会静默漏掉正确名字（上游原话："fails silently"）。本地 store 已存 raw_hash/profile/compare_mask，方向正确。
2. **每一部都要重捕 id 集合**。上游快照只覆盖 BO4/BOCW；捕获代码存在但默认关闭（`--features cordycep`）。本地项目的形态恰好绕开这一点：用户导入自己导出的哈希文件夹即等价于私有快照（store.import_exported + catalog_fingerprint）——这是本地相对社区版最大的结构性差异，应保持并强化（见 P2-3 的镜像策略）。
3. **命名惯例逐作重建**。上游实测：`_v2` 表的词 verbatim 拿来 hash 是死路（METHODS.md cross_era 注），降为 core 再按本作词法 respelling 有效（2,394,179 个新 core）。BOCW 的 `mcdp/` 材料目录、BO4 反斜杠声音名都是单作特性。上游 config 把 borrowed 名字定义为「候选，绝不计入惯例测量」——本地 autoplans 的 title-root 迁移要沿用这条纪律。
4. **在运营游戏（live title）快照会过期**。上游选 BO4/BOCW 的部分原因就是它们停更；MWII/MWIII/BO6/BO7/COD2026 都在更新，id 集合与 cod-name-db 表每天都在变（上游表格约一天 stale，start 负责刷新）。本地对应机制是 folder 重新导入 + fingerprint 失效重跑，需明确「过期策略」。

**结论**：上游的三步法可以直接搬；COD2026 以外的四作哈希证据已足够，堵点在于**目标 id 集合与每作词表/掩码的数据准备**，而非算法。这正是本地产品的既成形态（用户自带导出 + 本地验证 + Saluki 增量导出）可以稳稳接住的地盘。

## 4. 本地项目现状与差距

### 4.1 应保留的强项

- 18 profile / 8 算法族注册 + 10 游戏域预设（hashing.py PROFILES、presets.GAME_DOMAINS），覆盖 BO4→COD2026 的域划分在各作品 handler 源码级证据之上（docs/hash-algorithm-coverage.md）。
- Rust CPU + OpenCL GPU 双后端；OpenCL 内核设备侧拼串、**只回传命中位图**，恰好避开 acts 每候选 8 字节回传的结构性上限（docs/github-research.md §4 引 hashbrutegpu.cl）。
- 证据链纪律：完整键命中 → 纯 Python 独立回算 → 冲突剔除 → Saluki 已有键/名排除 → CDB 落盘回读；low60 降级待核验；calibration 准入（该资产类型必须有用此 profile 回算成功的真实样本才可搜）。
- SQLite WAL + 断点 + 控制文件暂停/取消 + 预算/节流。

### 4.2 差距对照

| # | 本地现状 | 上游机制 | 借鉴落点 |
|---|---|---|---|
| 1 | 后缀/目录前缀全部前向全量哈希（native hash_combinations 逐索引拼整串） | 剥离引擎，`run_best` 选便宜方向，尾代价从乘积改求和 | native + engine 增加 peeled 目标模式 |
| 2 | 算法注册五处手工同步（hashing.py、native Hasher、OpenCL KERNEL、presets.py、docs/hash-registry.json 镜像，代码不读 JSON） | —（上游单一 Rust 常量） | 注册表单一源 + 生成/CI 校验 |
| 3 | 无方法账本：evidence 有 method 字符串但无版本/指纹，无法按方法查询/复跑/判断耗尽 | submissions 全量运行记录 + METHODS.md 注册表 + methods_report | methods 表 + `finder methods` CLI + futility 守卫 |
| 4 | 重复运行同一 plan 重算已扫区间（仅按 position 记游标） | —（快照静态，天然幂等） | plan 指纹 + swept 区间位图，跨 run 跳过 |
| 5 | 无语料社群同步：只能本地导入 Saluki/CDB/WNI/词典 | fetch-tables 每日同步 cod-name-db csv | 可选只读导入 cod-name-db（默认关，许可见 §6） |
| 6 | 无预算预估：「一键计算」直接执行 | `confirm_plan --size` 事前报价 + 碰撞期望公示 | `finder run --estimate` + GUI 前置确认 |
| 7 | 生成器规则不进证据（crossassets/autoplans/weapon 的参数只在内存） | `--script` 把生成器拷进 run 并进 PR | evidence 增 method_id/method_version/generator_sha |
| 8 | Python 生成器是吞吐瓶颈（上游实测同形态 7.7×10⁵/s，确认器空闲 99%） | GPU.md 第 2 条建议：热生成器应先于 GPU 优化 | 热点生成器评估下沉 Rust（见 §6 风险） |

## 5. 改进方案（分三级）

### P0 正确性与域治理（先做，阻塞其他一切）

- **P0-1 注册表单一源**。以 `docs/hash-registry.json` 扩展为唯一事实源（增加 algorithm_id→native/OpenCL 编号映射、每 profile 的 status: evidence/candidate/unknown、test_vectors 指针），写生成脚本产出 `finder/hashing.py` 的 PROFILES/PROFILE 参数段、`native/src/lib.rs` 的算法分派、`finder/backends.py` KERNEL 编号、`presets.py` 的 GAME_DOMAINS；CI 增加一致性测试（与 tests/test_algorithms.py 同风格，保证 Python/Rust/GPU 三方对同一向量一致）。消除五处手工同步的漂移风险（本轮调研已发现该风险实际存在）。
- **P0-2 COD2026 分域门控**。注册表中 COD2026 拆为三层：**资产名/animpkg/声音库/声音文件域（iw-resource63）= evidence**（rex 表考古，§3.0），可正常选择；**声音银行别名域 = iw-resource63 表级规则的 Treyarch offset 满 64 位 profile**（若本地注册表缺此 profile 组合，按 §3.0 证据补登）；**脚本/dvar/omnvar 域 = unknown**，GAME_DOMAINS 不提供默认选择，需本地二进制的 hash/name 样本对（≥ 每域 N 对回算一致）才解除，证据写回 docs/hash-algorithm-coverage.md。
- **P0-3 证据元数据扩展**。evidence 表及导出增加 method_id、method_version、generator_sha、profile_id、mask_used；exporter 现有冲突剔除/Saluki 排除/CDB 回读逻辑不变，只增字段，保证新旧运行时互认。

### P1 引擎能力（核心增益）

- **P1-1 反向剥离引擎**。
  - 算法可逆性清单：FNV 族（iw_resource63、fnv1a63/64、secure 系 iw_dvar64/t10_script64/t10_sp_script64/t10_omnvar64 的尾段、suffix 追加型）prime 为奇数可逆；prime32/djb2-xor（33^{-1} 存在）可逆；**kvp64 尾端非线性混合、t89 的移位链不可逆**，继续前向。
  - masked(63) 处理：id 最高位已知为 0（引擎标志位），剥离中间态按满 64 位两侧匹配（上游 src/search.rs 同思路；数学公开，自研实现）。
  - 接口：`finder/candidates.py` 的 Plan 拆 head/stem/end 槽；engine 运行前 `run_best` 比较两个方向的成本；native 增加 peeled-target 批接口。
  - 验收：同一目标空间下「实际前向哈希数」较全前向下降 ≥100×（对标上游 218×）；新增 tests/test_peel.py：剥离结果与全量前向枚举**逐条一致**（含 secret 注入、斜杠/大小写归一化、63 位掩码、32 位算法边界）。
- **P1-2 计划估算层**。`finder run --estimate` 与 pipeline estimate：空间大小、候选总数、碰撞期望 `n×w/2⁶³`、预计耗时（可由 CPU 基准外推）；GUI 一键按钮改为「展示估算→确认→执行」，保留单页体验。
- **P1-3 幂等扫掠**。SQLite 增加 swept 表（plan_sha256, kind, begin_index, end_index）；任务恢复与重跑跳过已扫区间；与现有 position 断点对齐；重复运行同一 plan 的时间应趋近 0。

### P2 生态与度量（持续增益）

- **P2-1 方法账本**。methods 表（method_id, version, generator_sha, profile, targets, candidates, names, duration, first/last run）；`finder methods report` 输出按方法聚合的产率/衰减；同方法同目标连续 3 次 0 新名 → 拒绝运行（`--anyway` 覆盖），对齐上游 futility 语义。
- **P2-2 cod-name-db 只读同步 + 表考古工具（可选，默认关）**。sparse 拉取 csv/（git blobless checkout）；配套一个 `table-audit` 工具：对每张表、每个候选 profile 按行试算并输出「表 → profile」鉴定报告与回算率分组（§3.0 的脚本化，新作品表上线即可自动识别算法归属与掩码）。**导入纪律（§3.0 实测教训）：逐行回算后才进入 words/排除集；回算不中的行（iw9/s6 老路径组、rex_emitters 等，占本表大头）隔离为仅候选词汇，绝不当作已验证名称**；仅入不出（回流靠用户手工提交，见 §6 许可）。
- **P2-3 用户导出 = 私有快照的强化**。导出 folder 导入时保留 pool/type 元数据；提供「与 Saluki 索引的差集」视图（即本地版 coverage.py 的雏形）：哪些类型未命名最多、值不值得一夜。
- **P2-4 生成器沉淀**。crossassets/autoplans/weapon 的规则各分配稳定 method_id + 版本号（如 `crossassets.identity_substitution.v1`），参数随 evidence 落库；热点路径（800 万组合上限的 crossassets）评估下沉 Rust：上游实测 Python 管道是瓶颈，非哈希。
- **P2-5 跨作品词表纪律**。增加 borrowed 导入通道（文档明示：只作候选，不进校准、不计惯例）；把「verbatim 死、respelling 活」的测量结论写入 docs/hash-algorithm-coverage.md 的开发实施要求。

## 6. 风险与边界

- **许可**：上游 GPL-3.0；porter-lib GPL-3.0；cod-name-db 仓库**无 LICENSE**（再分发权未确认，docs/github-research.md §4）。对策：只读同步 csv、自研 CDB 读写（本地 formats.py 已是独立实现）、不做自动回流 PR。
- **可逆性是数学不是代码**：FNV 模逆为标准结论，自研实现无衍生风险；不得整段复制上游 Rust。
- **live 游戏漂移**：cod-name-db 日更 + 游戏补丁会使排除集/目标集过期；本地以 folder 重新导入 + fingerprint 重跑应对，需在 user-guide 明确「重新导入即刷新」。
- **GPU 纪律**：OpenCL 保持可选与 CPU 复核不变；上游实测与本地内核设计互相印证，不要退回 acts 式每候选回传结构。
- **碰撞率**：候选越多巧合匹配越多（上游 103 T pass 期望 1.5 个）。估算层必须公示该数字；low60 只进待核验的规则不变。

## 7. 验收标准

- 新增测试：test_peel.py（剥离=前向枚举）、test_registry_sync.py（注册表与三处实现一致）、test_methods.py（账本/指纹/futility）、test_estimate.py（估算与实测偏差上限）；tests/test_pipeline*、test_exported 全回归。
- **表考古回归**：把 §3.0 实测样本（rex_ 行 ≥ 20 条/域 + strings 60 位 + aliases 满 64 + bo2_sab SDBM）固化为 tests/fixtures 的参考向量，任何算法注册表改动后重跑，防止回归。
- 文档：hash-algorithm-coverage.md 增加「每作启用 checklist」（MWII/MWIII/BO6/BO7 的 per-table mask、声音域、bones32；COD2026 的资产/声音域已证实、脚本域待样本），未证实域不作承诺的纪律不变。
- 指标：剥离引擎全前向哈希数比、估算器误差、重复运行同 plan 的跳过率，写入 development-plan 或本文件附测量记录。

## 参考来源

- 上游 README.md / AGENTS.md / METHODS.md / docs/HASHES.md / docs/GPU.md / config.example.toml / scripts/README.md：https://github.com/KingslayerKyle/hash-slinging-slasher
- cod-name-db（社区表）：https://github.com/echo000/cod-name-db
- 本地：docs/hash-algorithm-coverage.md、docs/hash-registry.json、docs/github-research.md、docs/development-plan.zh-CN.md、finder/hashing.py、finder/presets.py、finder/candidates.py、finder/engine.py、finder/backends.py、finder/store.py、finder/exporter.py、native/src/lib.rs、tests/
