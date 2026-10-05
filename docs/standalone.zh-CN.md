# 在没有研究项目的电脑使用

要求 Windows 11 x64。解压完整便携包，双击启动工作台.vbs。无需 Python、Rust、Ghidra、原始研究项目或原始 assets.sqlite。不要只复制 exe，必须保留 _internal。

1. 项目与构建页填写作品/构建，在“导入已经导出的哈希资产”中选择本机文件夹；支持哈希命名的音频、图片等文件。未知模型不导入。
2. 作品与算法页选择作品及名称域，并应用规则；确认文件名完整位宽，低60位结果保持待核验。
3. 可在前作映射复用页导入自行提供的 CSV/CDB/WNI 名称词典。无需任何特定研究目录。也可以直接使用显式模板和 TXT/TSV 候选；哈希本身不携带可直接读取的真实名称。
4. 发现任务页配置关键词、候选和 CPU/GPU。CPU 始终可用；GPU 需要本机支持 OpenCL 的显卡驱动，自动模式可退回 CPU。
5. 导出页选择“已有名称索引”：可以是本机 Saluki 目录，也可以是从原电脑复制的 hash_pkg 或包含 CDB 的文件夹，无需运行或安装 Saluki。该索引用于严格排除已有名称。词典与索引不随软件分发。
6. 导出新增 verified.cdb / verified.csv。全部命中已在索引中时输出空增量报告。索引缺失或损坏时停止导出，避免意外包含已有名称。

工作库默认保存在当前用户 CODNameFinder 文件夹，也可在界面打开或新建；不要求 E: 或 D: 盘。按本机路径选择数据，勿使用原电脑绝对路径。

命令行示例（本机路径）：
```
CODNameFinder.exe --work C:\Data\work.sqlite import-exported C:\Data\hashed --game BO6 --profile iw-resource63
CODNameFinder.exe --work C:\Data\work.sqlite search C:\Data\search.json
CODNameFinder.exe --work C:\Data\work.sqlite export C:\Data\output --saluki-dir C:\Data\existing-indexes
```
