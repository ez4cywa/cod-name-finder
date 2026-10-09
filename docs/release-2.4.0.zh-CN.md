# 2.4.0 上游名称贡献

本版增加可预览、可选择的上游名称贡献流程，并统一输入控件与按钮的内容居中。名称计算仍使用Avalonia NativeAOT界面、内置Python后端、Rust CPU及可选OpenCL GPU；原有CSV/CDB增量导出、关联推测和离线快照流程继续可用。

Windows x64安装包：[CODNameFinder-2.4.0-Setup.exe](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.4.0/CODNameFinder-2.4.0-Setup.exe)。[2.4.0发布页](https://github.com/ez4cywa/cod-name-finder/releases/tag/v2.4.0)提供对应源码、SHA256和最终验证附件。用户无需Git、gh、系统Python/.NET或原研究项目checkout。

## 本版新增

- 上游贡献折叠区：先本地验证导出并生成离线预览，检查全部名称与about摘要；登录后线上排重，再手动创建PR。
- Token遮蔽显示，经标准输入传给后端，默认仅内存使用；显式勾选才保存到Windows凭据管理器，可检查账号和删除凭据。
- 本会话自动提交默认关闭。显式启用后，仅完整完成、有正式新增且不是低60位的运行会尝试投稿；失败不影响本地导出。
- 上线前检查同作品、同类型公开快照成员，检查现代7张社区v2表或BO4/BOCW全部CSV、全部已合并名称TXT、分页开放PR；提交前刷新状态。
- 公开blob按Git SHA校验缓存，元数据仍联网刷新。检查未完成时不跳过排重、不创建PR。
- 首版投稿类型为动画、图片、材质、声音文件、声音别名，作品为BO4、BOCW、MWII、MWIII、BO6、BO7、COD2026，仅接受ASCII名称。其他类型、非ASCII名称和未证域统计后保留本地；BO4声音no-fold域当前为candidate，不自动投稿。
- 公开内容仅分类名称TXT和about方法摘要。batch fingerprint只摘要公开名称批次，不是搜索计划指纹；数字统计使用本轮实际新扫描数和整轮耗时。数据库、原始证据、路径、关键词、配置参数、捕获、源语料及Saluki旧索引不上传。
- 一次最多10000条可投稿名称，超限明确要求拆批；单个证据文件和CDB解压内容限32MB。现代alias仍须本地原始完整64位证据，不因线上快照只存63位而放宽。
- 输入框、下拉框、按钮内容水平、垂直居中，长日志和预览正文保留可读的文本布局和滚动。

## 第一次使用

先按[一键教程](user-guide.zh-CN.md)完成自己的CSV/CDB导出。保留完整 `run-*` 和其中 `names-*`，再展开贡献区域，点击“预览提交”。没有Token且没有保存凭据时生成离线预览；用“打开完整预览”检查全部公开内容后，以公开仓库用途的经典PAT `public_repo` 登录，重新线上预览，最后点击“创建上游 PR”。

保存凭据不会开启自动投稿；每次启动自动提交仍关闭。界面处理本次完整运行结果；历史或partial运行中完整回算通过的名称可用内置命令行手动准备，`prepare --offline` 明确不读取凭据、不访问网络。详细权限、公开字段、网络缓存和失败处理见[上游贡献教程](upstream-contribution.zh-CN.md)。

公开fork可能需要等待异步创建，Token或账号策略可能限制写入；上游CI也可能需要维护者批准。PR创建成功表示等待审核，不代表名称已合并。

## 验证与边界

本版最终结果集中于发行附件 [CODNameFinder-2.4.0-validation.json](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.4.0/CODNameFinder-2.4.0-validation.json)，区分源码回归、HTTP/API与证据测试、前端桥接、NativeAOT和EXE安装验收。

真实网络验证只读；fork、分支、提交和PR等写入流程使用fake GitHub集成验证，不为验收创建真实findings PR。fake写入和合成桥接验证不等于真实账号已投稿、GitHub维护者已批准CI或PR已合并。

本版没有增加全游戏名称可逆保证，也没有新增BO7现场捕获、Saluki GUI现场加载、第二台物理电脑或八小时持续运行的现场结论。2026-10-05的MW7 Beta现场记录与2.3.0的741项源码回归继续保存在[2.3.0历史发布说明](release-2.3.0.zh-CN.md)，不能代替2.4.0的最终验收。
