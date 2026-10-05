# BO4—COD2026 哈希算法覆盖规格

日期：2026-10-05。已阅读本地 `E:\ghidra_12.1.3_PUBLIC_20260817\analysis\atian-cod-tools\src\core\shared\utils\hash_mini.hpp`，并核对 GitHub 当前公开同名源码。这里区分「函数实现已公开」和「某游戏某名称域确实采用该函数」；不宣称有限资料能够证明所有游戏的全部哈希。

## 精确算法目录

定义：`N` 为 ASCII A-Z→a-z、反斜杠→正斜杠，其余字节不变；输入不包含终止 NUL（T7 的额外乘法除外）。`F(s,o,p,w)`：h=o；逐字节 h=((h XOR N(c))*p) mod 2^w。63 位函数使用 64 位迭代，最后 AND `0x7FFFFFFFFFFFFFFF`，不是每轮 63 位截断。32 位溢出每轮按 modulo 2^32；右移为无符号逻辑右移。

| 注册 ID | 常量与公式 | 输出 |
|---|---|---|
| fnv1a64_normalized | F(s,0xCBF29CE484222325,0x100000001B3,64) | 64 |
| fnv1a63_normalized | 同上最终 AND 0x7FFFFFFFFFFFFFFF | 63 |
| fnv1a32_normalized | F(s,0x811C9DC5,0x1000193,32) | 32 |
| iw_resource63 | F(s,0x47F5817A5EF961BA,0x100000001B3,64) AND 0x7FFFFFFFFFFFFFFF | 63 |
| iw9_script64 | F(s,0x79D6530B0BB9B5D1,0x10000000233,64) | 64；公开头文件无63位mask |
| t7_script32 | F(s,0x4B9ACE2F,0x1000193,32)，再乘 0x1000193 modulo 2^32 | 32 |
| t89_script32 | 见下方专用公式 | 32 |
| iw_dvar64 | SEC(s,0xD86A3B09566EBAAC,0x10000000233,"q6n-+7=tyytg94_*") | 64 |
| t10_script64 | SEC(s,0x1C2F2E3C8A257D07,0x10000000233,"zt@f3yp(d[kkd=_@") | 64 |
| t10_sp_script64 | F(s+"zt@f3yp(d[kkd=_@",0x1C2F2E3C8A257D07,0x10000000233,64) | 64 |
| t10_omnvar64 | SEC(s,0xCBF28CE593123345,0x100000002C1,"gvbs9*vpm@mh@krh") | 64 |
| prime33_add32 | h=5381；h=(33*h+N(c)) mod 2^32 | 32 |
| djb2_xor32 | h=0；h=((33*h) XOR N(c)) mod 2^32 | 32 |
| kvp_weighted64 | acc=0，mul=119；每字节 acc=(acc+mul*N(c)) mod 2^64，mul++；最终 acc XOR ((acc XOR (acc>>10))>>10) | 64；字段可能截断，应另设存储profile |

`SEC`：空字符串返回0；非空在首字节后插入固定字符串，按 F 的规范化运算。与普通的 `s+salt` 不同。公开 C++ API 的非零 start 参数代表续算，跳过再次插入安全字符串；新应用应明确区分完整计算/续算。

`t89_script32`：h=0x4B9ACE2F；每字符 t=(h+N(c)) mod 2^32；v=t XOR ((t<<10) mod 2^32)；h=(v+(v>>6)) mod 2^32；结束 v=9*h mod 2^32；结果=0x8001*(v XOR (v>>11)) mod 2^32。

以上来源：[hash_mini.hpp](https://github.com/ate47/atian-cod-tools/blob/5d4d1ee6f7676f4529b99fc89c2382dde8b856b7/src/core/shared/utils/hash_mini.hpp)。HashIndex 文档将 MWII/III Scr 写为63位，但上述源码返回完整64位，必须保留 **full64** 与 **stored63** 两个profile，不能静默混淆。来源：[HashIndex 算法说明](https://github.com/ate47/HashIndex/blob/main/docs/hashes.md)。

### 声音域额外算法

Greyhound 的 SAB 源码还有 `HashSoundString`：h=5381；h=(lowercase(c)+(h<<6)+(h<<16)-h) mod 2^32，即 multiplier 65599 的 SDBM 形式；**不是 FNV32，也不是 DJB2**。`HashSoundStringV17` 为标准 offset/prime 的 FNV1a64，仅 `tolower`，不将反斜杠改成正斜杠。必须作为独立 `sab_sdbm32_lowercase` 与 `sab_fnv1a64_lowercase` 注册。源码的 `tolower` 受字符/locale条件影响，先限制可验证ASCII，不能随意用Unicode casefold替代。来源：[SABSupport.cpp](https://github.com/Scobalula/Greyhound/blob/master/src/WraithXCOD/WraithXCOD/SABSupport.cpp)。SAB容器名称、bank XAsset名称、alias、音频文件名可以处于不同名称域，不能共用一个“声音哈希”。

## 游戏与名称域覆盖

标记：证据=公开reader/compiler明确调用；候选=算法存在或文档提及，但当前具体build还要样本核验；未知=本次没有足够来源。

| 游戏 | 资产/资源名称 | 脚本字段/函数 | 其他域 |
|---|---|---|---|
| BO4 | fnv1a63（公开文档） | t89_script32；早期VM31为t7_script32 | structuredtable键 prime33_add32、KVP weighted；声音bank与独立SAB须按容器核验 |
| BOCW | fnv1a63（公开文档） | t89_script32 | KVP weighted（linker调用）；其他候选先按名称域验证 |
| MW2019 | reader的GetXAssetNameHash调用iw_resource63；不意味着所有资产只存hash | 当前未确认该项目对其全部脚本域覆盖 | pool类型名称 fnv1a32；SAB按header版本选择，待样本对齐 |
| Vanguard | reader的GetXAssetNameHash调用iw_resource63 | 未确认全部脚本域 | SAB 0x11 对应Vanguard；声音名称可用独立SAB FNV64 profile验证 |
| MWII | iw_resource63 | iw9_script64，保存位宽按域核验 | iw_dvar64（公开文档）、tag/pool fnv1a32 |
| MWIII | iw_resource63 | iw9_script64 | iw_dvar64；tag/pool fnv1a32 |
| BO6 | iw_resource63；部分value和#运算符fnv1a64 | t10_script64；战役指定VM采用t10_sp_script64 | iw_dvar64、t10_omnvar64、tag/pool fnv1a32；soundbank unlinker登记IW资源hash |
| BO7 | iw_resource63；VM sat16 #为fnv1a64 | sat15–1a公开VM配置复用t10_script64 | sat16 明确注册iw_dvar64、t10_omnvar64、tag fnv1a32；soundbank登记IW资源hash |
| COD2026 | `rex_` 资产、动画包、声音库及 `rex/` 声音路径已逐行证实 `iw-resource63` | 未确认，默认门控 | 声音银行 alias 为 Treyarch offset 满64位 `fnv1a64`；脚本 / dvar / omnvar 不由资产算法推定 |

这里“证据”证明社区实现怎样处理该游戏，不自动等价于官方规范或用户本地build实测；最终启用状态必须由该build的名称/hash对确认。

公开来源链接（本地同路径同时已检查）：

- [MW2019 handler](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/handler_game_mw19.cpp)、[Vanguard handler](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/handler_game_vg.cpp)。GetXAssetNameHash用于名称索引/验证，即便某资产原本有明文名称仍会调用，不能据此断言全池存储都是hash。
- [MWII handler](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/handler_game_mwii.cpp)、[MWIII handler](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/handler_game_mwiii.cpp)。
- [BO6 handler](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/handler_game_bo6.cpp)、[BO7 handler](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/handler_game_bo7.cpp)。
- [BO7 sat16 VM](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/gsc/opcodes/gsc_opcodes_sat_16.hpp)：同时注册 #/@/%/t/s/o，不同名称域不可混成一种“BO7哈希”。
- [BO4 early VM31](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/gsc/opcodes/gsc_opcodes_t8_31.hpp)、[BO6 campaign VM0b](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/gsc/opcodes/gsc_opcodes_t10_0b.hpp)、[VmInfo hash dispatch](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/gsc/gsc_opcodes.cpp)。
- [BO4 structured table linker](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/linkers/bo4/linker_bo4_structuredtable.cpp)、[BO4 KVP linker](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/linkers/bo4/linker_bo4_keyvaluepairs.cpp)、[CW KVP linker](https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/linkers/cw/linker_cw_keyvaluepairs.cpp)。

## 开发实施要求

1. 算法注册表与游戏profile分离；profile至少包含game/build/domain/algorithm/normalization/storage_width/compare_mask/source/status/test_vectors。
2. `MASK60=0x0FFFFFFFFFFFFFFF` 的跨索引初筛仍只能进待核验区；但 `fnv1a_strings.csv` 是 BOCW **实际存储60位**的表，独立注册 `fnv1a60`，不能将该表误用63位 profile。二者区别在于明确的表/域证据，不是出现了新的数学哈希函数。
3. 可选择全算法搜索，但只在目标域与profile匹配且CPU复核后自动导出；跨算法命中单独记录，不能冒充原名。
4. 每算法至少加入空串、A/a、路径斜杠、最长长度、前缀续算、多位宽、已知真实名称/hash测试；CPU/GPU需同向量一致。非ASCII行为必须单独profile，公开char实现有符号转换差异。
5. 现代资产名与SAB字符串分别规范化。默认“不扩展材质”只过滤目标资产类型；关键词语料来自材质时仍可能帮助模型命名，应作为独立用户选项。
6. XXH32/64、CRC、SHA等存在于工具菜单并不证明它们用于这些游戏的名称；没有域证据前仅放通用工具区，不列为已证实游戏资产算法。
7. COD2026 只对已有逐行回算证据的资产、动画包、声音库、声音文件和 alias 域提供默认规则；脚本字段 / 函数、dvar、omnvar 的规则保持 unknown。用户显式允许未证实域也必须通过原有真实样本校准，不能跳过 CPU 复核。

## 2.1 单一注册表与每作启用检查

`docs/hash-registry.json` 是唯一可编辑的常量、编号、作品域和表级映射来源。执行 `python scripts/generate_hash_registry.py` 会生成 Python 包内数据、Rust 编号常量和 NativeAOT C# 元数据；`--check` 与 `tests/test_registry_sync.py` 拒绝过期生成物。OpenCL 内核使用生成的编号宏，不再维护数字副本。运行时核对 Python / DLL 的注册表 SHA256，混装旧 DLL 会明确报错。新电脑只读取包内生成数据，不需要此 docs 文件或 Ghidra 研究目录。

当前共 20 个 profile、8 个算法族；新增 `fnv1a60` 是字符串表的实际位宽，`fnv1a63-no-fold` 是声音路径的候选规范化变体。后者没有被全表推定为 BO4 的所有声音规则：需提供对应导出名称/键样本进行校准。旧配置只选显式 profile 的行为继续兼容；新配置明确区分名称域与导出资产类型。例如 `.gsc` 文件的 XAsset 名仍属资产域，其内部脚本函数名属另一个域。

| 启用作品 | 必须检查的表 / 域 | 可用默认 | 尚需检查 |
|---|---|---|---|
| BO4 / BOCW | 普通资产与语言声音表；BOCW strings 表 | 资产 Treyarch63，strings Treyarch60 | BO4 反斜杠声音路径需单独 no-fold 样本；不能用下划线导出显示名替代完整路径 |
| MWII / MWIII | `_v2` 资产与 soundbanks；`bones`；`aliases_v2` | IW63；bones **FNV32**；aliases **Treyarch满64** | 真实目标导出及本作语料；脚本 stored63 与 full64 分开 |
| BO6 / BO7 | `_v2` 资产与 soundbanks；`bones_v2`；`aliases_v2` | IW63；bones_v2 / aliases **Treyarch满64** | 脚本、战役 VM、dvar、omnvar 按各域 profile 校准 |
| COD2026 | `rex_` 资产 / animpkg / bank 与 `rex/` 声音路径；rex alias | IW63；alias **Treyarch满64** | 脚本 / dvar / omnvar 默认 unknown，缺真实 build 样本不启用 |

`bones_v2` 满64位来自上游作者的[逐表说明](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/main/docs/HASHES.md)，并用社区真实行回算验证；用户参考方案 §3.1 的“bones32”概括仅适用于 `fnv1a_bones.csv`，不能扩展到 BO6 / BO7 的 `bones_v2`。

## 表考古、社区导入与跨作纪律

2026-10-05 通过软件的 HTTPS 只读同步模块固定到 cod-name-db commit `0f010f756a1f33b8961f3eb43d40bf1a4cd91c75`，同步全部 40 张 CSV 表。以 `rex` 过滤逐行试算 8 个主要候选 profile，共检查 **32,011** 行。`xanims_v2` 5,169/5,169、`ximages_v2` 1,066/1,066、`xmaterials_v2` 778/778、`animpkgs_v2` 526/526、`soundbanks_v2` 185/185 均匹配 IW63；`aliases_v2` 373/373 匹配 Treyarch 满64位；strings 巧合子串 7/7 匹配60位，BO2 SAB 11/11 匹配 SDBM。全部逐表/路径组结果及原文件 SHA256 记录在 `validation/community-registry-rex-audit.json`。

公开回归 fixture `tests/fixtures/community-table-vectors.json` 使用 220 条原创合成名称，覆盖 11 张表路由、每表20条；固定预期键由独立 MIT C++ 参考和独立 SDBM 算式计算。纯 Python、Rust CPU、实际可用 OpenCL GPU 对同一组键逐项一致。公开源码和 EXE 安装包均不附带 cod-name-db 的原始表行；上段真实社区表测量是私有历史验证，合成回归只验证算法与导入路由，不替代真实作品证据。`rex/` 声音路径 22,813/22,813 匹配 IW63；`iw9` / `s6` 等混合组没有被提升为同等证据。语言声音表中的 rex 巧合子串也有回算失败行（例如 English 1/2），不会整表放行。

社区同步默认关闭，只读且固定 HTTPS 源，无自动提交。缓存以 upstream commit 和内容 SHA256 标识新鲜度，不以本地文件修改时间冒充上游日期。未知表、显示名重建导致的名称/键不一致逐行进入 `quarantined`，只提供候选词汇；只有 `verified` 能用于校准和排除。`borrowed` 导入即使来源键可回算，也强制仅候选，既不补校准样本，也不计本作惯例或已确认名称。已有名称原样跨作移植通常缺少产率，去除作品根、提取身份词段并按本作真实模板重新拼写是可测量的方法；算法命中仍须 CPU 复核，不能把跨作候选标签改成验证证据。

每次游戏更新后重新扫描用户导出目录、更新目录指纹；只有目标指纹和完整计划指纹未变的扫掠才可复用。更新社区表须由用户主动刷新；回算失败的旧路径组不会因为本作更新而自动变成可校准样本。

固定社区来源为 [cod-name-db 上述 commit](https://github.com/echo000/cod-name-db/tree/0f010f756a1f33b8961f3eb43d40bf1a4cd91c75/csv)。表级规则的直接依据是上游 [HASHES.md](https://github.com/KingslayerKyle/hash-slinging-slasher/blob/main/docs/HASHES.md)：该版本明确将 `bones.csv` 归于 MWII / MWIII、将 `bones_v2.csv` 归于 BO6 / BO7 / WZ Mobile，故没有凭“v2”字符串推定 MWII / MWIII 同时支持 bones_v2；用户手动选择其它位宽仍须真实目标域样本。
