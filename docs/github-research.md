# GitHub / Saluki 兼容性研究

研究日期：2026-10-02。仅采用仓库源码、仓库维护者文档和 GitHub API；未运行 Saluki。下列结论为开发设计依据，不代表 COD 2026 算法已经验证。

## 1. cod-name-db 能提供什么

检查快照 `650861e1ae6d0a4896dc3df7f2eba0cb50ea26e7`。仓库是名称映射 CSV 数据及 CSV↔CDB 工具，不是自动反解器。CSV 无表头，第一列为不带 `0x` 的十六进制 u64，第二列为名称；工具用 `u64::from_str_radix(key_str, 16)` 解析。坏行输出错误并继续，因此新应用应增加严格校验及导入报告。相同 hash 存进 HashMap 会覆盖旧值，新应用必须先保留冲突记录。来源：[转换代码](https://github.com/echo000/cod-name-db/blob/650861e1ae6d0a4896dc3df7f2eba0cb50ea26e7/src/name_index_gen.rs)。

实际依赖是 **echo000/porter-lib**，不是直接依赖 dtzxporter 上游。来源：[Cargo.toml](https://github.com/echo000/cod-name-db/blob/650861e1ae6d0a4896dc3df7f2eba0cb50ea26e7/Cargo.toml)。数据文件按游戏、算法、资产族混合分组，不能仅凭文件名推导全部资产类型或游戏兼容性。来源：[csv 目录](https://github.com/echo000/cod-name-db/tree/main/csv)。

## 2. 可实现的 CDB 格式

echo000/porter-lib 检查快照 `035f0e08a18ea535db8bf38cb8c62dbd46c20874`。`NameDatabase` 写入：

1. 16 字节头：little-endian u32 magic=`0x42444E50`（字节为 PNDB）、entry_count、compressed_size、decompressed_size。
2. 剩余字节为 **LZ4 raw block** 压缩数据；不是 ZIP，也不是通用 LZ4 frame。
3. 解压载荷先顺序写 N 个 NUL 终止名称字符串，再写 N 个 little-endian u64 hash，两个数组按位置配对。
4. 当前依赖保存前按名称排序；转换仓库中“顺序每次不同”的 TODO 已不能完整描述目前依赖行为。为稳定输出，应自行定义 name/hash 二级排序。

来源：[NameDatabase 源码](https://github.com/echo000/porter-lib/blob/035f0e08a18ea535db8bf38cb8c62dbd46c20874/crates/porter-utils/src/name_database.rs)，[HashIndex CDB 说明](https://github.com/ate47/HashIndex/blob/40bdb5f7a34ad361d34db30beaee1346e5d7a22d/docs/cdb.md)。

CDB 本身只有 hash/name，不能保存游戏、资产类型、证据、算法或置信状态。因此 SQLite 为主库，CDB 仅作为验证后结果导出格式，另附 manifest/CSV。验证包括独立 reader 回读，以及 Saluki 实际加载小样本；仅写出 PNDB 不等于完成端到端兼容。

## 3. 哈希算法和掩码风险

HashIndex 给出多个引擎版本与资产/脚本类别的映射，包括普通 FNV-1a 63/64、IW Resources、MWII/III Scr、BO6 安全字符串变体。模型资源相关候选 **IW Resources** 使用 offset `0x47F5817A5EF961BA`、prime `0x100000001b3`，输出 63 位；不能把脚本 hash 当成模型 hash。来源：[算法文档](https://github.com/ate47/HashIndex/blob/40bdb5f7a34ad361d34db30beaee1346e5d7a22d/docs/hashes.md)。

实际可借鉴实现 `hash_mini.hpp` 会将 ASCII A-Z 转小写、反斜杠转正斜杠，再迭代 `(h ^ c) * prime`；各算法掩码不同。文档与源码有潜在差异，例如脚本函数的最终位宽，应以目标二进制和已知测试向量为最终依据。来源：[独立 MIT 头文件](https://github.com/ate47/atian-cod-tools/blob/5d4d1ee6f7676f4529b99fc89c2382dde8b856b7/src/core/shared/utils/hash_mini.hpp)。

HashIndex 建议查询用 60 位 mask，但这是跨数据集检索约定，**不应盲目改变原始 hash**。应存 raw_hash/profile/compare_mask，将 60 位命中标为候选，再按目标引擎规则复核。哈希相等证明“这个候选字符串符合当前函数”，不单独证明它就是唯一历史原名。

## 4. 借鉴项目与许可

| 项目 | 可借鉴内容 | 已核实许可 |
|---|---|---|
| echo000/cod-name-db | 名称语料、CSV/CDB 工作流 | 仓库根目录未见 LICENSE，GitHub API license=null；数据再发布权须确认 |
| echo000/porter-lib | CDB 实际读写实现 | GPL-3.0，直接链接/复制时需按其条件评估 |
| dtzxporter/porter-lib | 上游 NameDatabase | GPL-3.0 |
| ate47/HashIndex | 多来源索引、格式说明 | MIT；仍需保留来源与原始数据溯源 |
| ate47/atian-cod-tools | CPU hash、OpenCL GPU、字典/字符组合、目标匹配 | LICENSE.md 明示 MIT 或 GPL-3；具体文件与依赖须分别核对 |

来源：[cod-name-db API](https://api.github.com/repos/echo000/cod-name-db)、[porter-lib LICENSE](https://github.com/echo000/porter-lib/blob/main/LICENSE)、[上游 LICENSE](https://github.com/dtzxporter/porter-lib/blob/main/LICENSE)、[HashIndex LICENSE](https://github.com/ate47/HashIndex/blob/main/LICENSE)、[Atian LICENSE](https://github.com/ate47/atian-cod-tools/blob/5d4d1ee6f7676f4529b99fc89c2382dde8b856b7/LICENSE.md)。

Atian 的 OpenCL 内核支持前缀/后缀、词组合、中间分隔符、多算法开关，并将 hash 按 60 位比较，目标桶内二分搜索。它可以指导批次任务和索引设计，但不能直接将其匹配结果标作 COD2026 已验证原名；CPU 复核需保留完整位宽及来源。来源：[GPU 内核](https://github.com/ate47/atian-cod-tools/blob/5d4d1ee6f7676f4529b99fc89c2382dde8b856b7/config/data/opencl/hashbrutegpu.cl)。

## 5. 尚未确认

- 本次未找到并审计 Saluki 当前公开 reader 源码；`dtzxporter/Saluki` API 请求未成功，不据此断言该源码不存在。CDB 与 Saluki 的关系由 cod-name-db 作者 README 和 HashIndex 维护者说明支持，安装路径、自动刷新、优先级、掩码规则须用用户当前 Saluki 版本实测。
- COD2026 的实际资源 hash、标志位、资产类型字段必须由本地研究项目与导出的已知样本验证；BO6/MWIII 算法不能直接冒充 COD2026 已证实算法。
- 未做数据库规模统计、全库冲突统计或 CPU/GPU 性能测试；不承诺吞吐与破解率。
- 只有关键词没有未知 hash 清单时，可以生成候选，但无法判定候选属于实际目标资产。应先导入资产 hash/type/game/build 清单。
