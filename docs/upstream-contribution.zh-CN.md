# 将发现的名称贡献给上游

适用版本：**2.4.0**。本功能把本地已完整验证的新名称整理成 [KingslayerKyle/hash-slinging-slasher](https://github.com/KingslayerKyle/hash-slinging-slasher) 的名称贡献PR。先完成本地CSV/CDB导出，再预览和选择是否公开。新电脑不需要Git、gh、系统Python/.NET、游戏、Ghidra或原研究项目checkout。

本会话自动提交默认关闭。没有Token且没有已保存凭据时可以纯离线预览；创建PR需要登录、线上检查通过和可投稿的新名称。任何投稿故障都保留本地导出。

## 第一次操作

1. 按[使用教程](user-guide.zh-CN.md)完成一次自己的资产名称计算。附带示例是流程测试数据，不应拿来向上游投稿。
2. 本轮完整完成且正式新增大于0后，展开“上游名称贡献 · Hash Slinging Slasher”。界面直接使用本轮的 `names-*` 导出。保留其上一级 `run-*` 中的 `work.sqlite`、`report.json`、`configuration.json`，不要只留下 `new_names.csv`。
3. 在未提供Token、也未保存凭据时点击“预览提交”，生成离线清单，再点击“打开完整预览”，阅读拟公开的about摘要和**全部**名称。界面长预览最多显示64K字符，完整文件才包含全部内容。离线清单仍可能包含社区或别人PR中已有的名称，不能直接当作线上新发现。
4. 按下一节创建Token，在软件的遮蔽输入框粘贴，点击“检查登录”确认账号。首次可以不保存凭据。
5. 登录后重新点击“预览提交”，等待同作品、同类型线上快照检查和完整排重。查看剩余条目、不支持数量及各项排除数量，再打开新的完整预览。
6. 确认愿意公开这些名称后，点击“创建上游 PR”。软件在自己的公开fork中准备分支、名称文件与about摘要，然后向上游默认分支申请合并。
7. 成功后点击“打开 PR”，阅读GitHub上的检查和维护者反馈。创建成功不等于已合并，也不改变本地名称计算结果。

只想使用本地工具时，可以始终保持贡献区关闭。上游投稿与“社区只读同步”是两个独立选项：开启同步不会自动提交PR。

## 登录 GitHub

本版跨个人公开fork创建PR使用 **Personal access token (classic)** 的 `public_repo` 权限。此流程只适用于公开仓库；不要求 `repo`、`workflow`、组织管理或删除仓库权限。`public_repo` 允许操作公开仓库，权限不只绑定某一个fork，应为该用途单独创建有期限的Token。[GitHub官方权限范围说明](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps)

1. 在浏览器登录你要用于投稿的GitHub账号，打开[经典Token申请入口](https://github.com/settings/tokens/new)。
2. 确认是 **Tokens (classic) → Generate new token (classic)**，填写用途并选择有效期。
3. 勾选 **`public_repo`**，创建并复制Token。具体入口、有效期和撤销方式见[GitHub官方Token教程](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic)。
4. 回到软件的Token框粘贴，点击“检查登录”；显示的账号应是你准备公开投稿的账号。

GitHub建议一般场景优先采用细粒度Token，但其官方说明仍列出“为不属于本人、且本人不是成员的公开仓库做贡献”的限制；本版这个跨个人公开fork流程采用上述经典Token。其他Token类型或组织策略不保证适用。[官方限制说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#fine-grained-personal-access-tokens-limitations)

Token框使用遮蔽显示。凭据经标准输入传给内置后端，默认只在进程内存使用，不写入命令行参数、普通偏好、配置文件或日志；API认证只发往 `api.github.com`。

### 保存、检查和删除凭据

- **不保存：** 保持保存凭据选项关闭，本次在内存中使用Token。下次启动重新提供凭据。
- **保存：** 显式勾选“保存至 Windows 凭据管理器”，点击“保存凭据”，或在勾选状态下进行线上预览后，存入当前Windows用户的凭据管理器，目标名为 `CODNameFinder:github.com:upstream-submission`，不写进 `settings.json`。以后可复用该凭据检查账号和进行线上预览。
- **检查：** 点击“检查登录”确认当前账号与保存状态；不会显示Token全文。
- **删除：** 点击“删除保存凭据”移除本机保存项。仅清空输入框不会删除凭据管理器中的Token；删除保存项也不会清空当前输入框。需要彻底使Token失效时，再到GitHub的Tokens页面删除它。[GitHub撤销步骤](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#deleting-a-personal-access-token)

记住登录不等于授权自动投稿。每次启动软件，本会话自动提交仍为关闭。

## 哪些名称可以投稿

本地计算支持21种非模型资产，首版投稿支持其中5种：

| 本地资产类型 | 上游名称清单类型 | 适用说明 |
|---|---|---|
| `xanim` | `xanim` | 动画名称 |
| `image` | `image` | 图片名称 |
| `material` | `material` | 材质名称；计算时需取消材质排除 |
| `sndasset` | `sound_asset` | 声音文件完整名称 |
| `soundbankalias` | `sound_alias` | 声音别名；现代作品必须有完整64位证据 |

| 软件作品 | 上游作品标识 |
|---|---|
| BO4 | `BLKOPS04` |
| BOCW / Cold War | `BLKOPSCW` |
| MWII | `MODWAR22` |
| MWIII | `YAMYAMOK` |
| BO6 | `BLACKOP6` |
| BO7 | `BLACKOP7` |
| COD2026 | `MODWAR7` |

投稿名称限ASCII，以保证上游的字节级大小写处理与本地验证一致。中文等非ASCII名称仍可本地导出，但本版计入不支持项，不投稿。其他16种类型、不支持的作品、未证域、来源表已有名称和类型不能唯一判定的行会保留本地并统计原因，不会被强行换类型投稿。BO4声音的 `fnv1a63-no-fold` 当前在本地注册表中仍为candidate，因此不自动投稿。

本地原始完整键与线上快照承担不同检查：本地证据证明名称在正确profile下完整回算成立；线上快照证明对应作品的同类型资产包含该键。现代CODIDS快照只存63位，因此线上成员检查不能取代声音别名的本地完整64位验证。低60位初筛候选不投稿，未知模型始终排除。

只有实际发现方法 `discovered` 形成的完整证据进入准备流程；catalog/prior来源不会被重新声称为本工具发现。同一hash落入多种类型又无可靠类型约束时，记为歧义并跳过。

## 投稿前检查了什么

本地检查从完整 `names-*` 和相邻工作库读取，不修改原文件：

1. 核对manifest列出的SHA256，要求新增CSV、验证CSV/CDB、分类CDB以及两种证据文件一致。
2. 核对工作库的目标作品、profile、输入指纹、原始目标类型和完整比较掩码，再以独立CPU算法完整回算名称。
3. 快照输入还要求对应记录属于已纳入的类型，并保留该profile需要的完整位宽；不会把masked63升级成满64。
4. 仅提取白名单字段。工作库仍有未合并WAL时，先结束运行再重试；不会为准备投稿迁移或写入数据库。

登录后，线上检查固定读取当前提交：

1. 对应作品的公开 `.ids` 与池清单：要求同作品、同类型成员匹配。
2. `echo000/cod-name-db`：现代作品检查7张对应的v2表；BO4/BOCW检查全部CSV。
3. 上游所有已合并名称TXT。
4. 分页读取的全部开放PR及其相关名称文件。

已有完整键、masked63键或保守归一化后相同名称都会作为排除线索。归一化仅用于避免重复投稿，不会替换上传名称，更不能把显示名当作已验证名称。社区CSV、已合并清单或开放PR无法完整读取时，软件停止投稿检查并保留本地结果。

提交前再次确认上游、社区提交与开放PR状态。网络中断或状态变化后可以重新预览；不要把离线缓存当作已完成的线上排重。

### 首次网络检查为什么较慢

首次检查可能下载较多公开快照、社区CSV与已合并TXT。缓存位于 `%LOCALAPPDATA%\CODNameFinder\upstream-cache`，按Git对象SHA核对和复用公开blob。已有相同内容不必重复下载，但仓库提交、树和开放PR状态仍需联网刷新。

此缓存不包含Token或本地资产。正常离线计算不需要这些公开缓存；删除缓存后下次线上检查会重新下载。遇到限流时等待后重试，不会改为跳过某一排重来源。

## 预览与公开文件

本地准备目录位于本轮 `run-*/upstream-contributions`，包含完整 `preview.md`、公开文件子目录和本地投稿状态。预览显示about摘要及每一条拟公开名称，不能只凭“新增数量”判断内容。

最终PR仅包含分类名称TXT和 `about_*.md`，目录为 `submissions/{login}-{digest8}_{TAG}_{stamp}/`，结尾保留上游标准作品标识与时间。每条名称使用上游的 `hash,name` 文本形式，按**第一个逗号**分割；名称本身包含逗号时仍保留原文，不套CSV引号。前后空白、ASCII控制字符或DEL会被拒绝，避免上游trim改变待验证字符串。

about包含作品、工具版本、方法ID、公开名称数量、类型计数、线上检查提交，以及本次候选数和总耗时。其中batch fingerprint只摘要本次拟公开的类型、完整键和名称批次，不能当作搜索计划指纹。候选数是本轮实际新扫描数；总耗时包含准备和导出，不伪造逐方法哈希耗时。完整缓存复用时如实报告本次0次新扫描，不把它当作原发现的运算成本。

以下内容只留在本地：

- `work.sqlite`、原始manifest、evidence、report、configuration和本地投稿状态文件。
- 本机目录、搜索关键词、生成器完整参数、输入SHA/目标快照指纹、原始捕获及源语料。
- Saluki原索引、`saluki-ready`合并索引、游戏文件和Token。

软件不会把整个run目录、public目录之外的文件或完整社区数据库附到PR。

单个本地证据文件及CDB解压内容限32MB；一次准备最多10000条可投稿名称。超限会明确失败，需要按资产类型或输入范围重新分批计算并预览，软件不会静默丢弃后面的行。不要通过手改CSV、manifest或工作库实现拆批。

## 什么时候使用本会话自动提交

先完成一次离线和线上手动预览，了解公开内容，再按需要显式开启自动提交。该选项仅对本次软件会话有效，重启后关闭，也不会因保存Token自动开启。

只有本次计算完整完成、正式导出新增项大于0且未使用低60位初筛时，才尝试线上准备和创建PR。停止或预算不足的partial运行不会自动触发；其中已完整验证的名称仍可按下一节通过内置命令行手动预览。没有可投稿类型、全部已知、权限或网络检查失败时，不创建PR，本地结果保持可用。

## 历史或partial导出的手动准备

界面贡献区使用本次完整运行结果，不提供历史导出目录选择。要检查以前的结果，或预算不足、停止的partial运行中已完整验证的名称，在安装目录打开PowerShell，运行以下离线预览命令。把示例路径替换为完整导出的 `names-*`；保留上一级工作库、报告和配置。

```powershell
.\CODNameFinder.exe upstream prepare --export "D:\NameFinderData\Results\run-20261009-120000\names-20261009-120100" --offline
```

`--offline` 只适用于prepare，明确不读取Windows已保存凭据，也不访问网络。返回结果中的 `preview_path` 指向完整预览，`package_dir` 是本地准备包。路径是本地状态，不会写入公开about。

先在界面按前文保存并检查凭据，再去掉 `--offline` 重新准备同一目录，完成线上检查：

```powershell
.\CODNameFinder.exe upstream prepare --export "D:\NameFinderData\Results\run-20261009-120000\names-20261009-120100"
```

阅读这次返回的完整预览后，才用实际返回的 `package_dir` 手动提交：

```powershell
.\CODNameFinder.exe upstream submit --package "D:\NameFinderData\Results\run-20261009-120000\upstream-contributions\实际准备包目录"
```

没有保存凭据时，省略 `--offline` 仍只生成离线预览，不能提交。Token不应写成命令行参数或脚本字面值；首次操作优先使用界面的遮蔽输入框。以上命令不会为partial运行开启自动投稿，也不会修改原来的导出。

## 常见问题

| 提示或现象 | 处理方法 |
|---|---|
| 离线预览有名称但不能提交 | 登录后重新预览，完成线上成员检查和排重 |
| 空Token框仍在联网 | 可能保存过凭据；清空输入框不会删除Windows凭据管理器项 |
| `unsupported`数量大于0 | 核对5种投稿类型、7部作品、ASCII名称、完整profile及类型歧义；这些结果仍保留本地 |
| 界面的预览按钮不可用 | 本次需完整完成、有正式新增且非低60位；历史或partial结果按命令行步骤手动准备 |
| 已有本地结果却不在上游快照中 | 本轮不投稿该行；上游公开快照可能不含你的加载集合，不能借其他作品快照通过检查 |
| SHA或证据集合不一致 | 恢复完整导出与相邻工作库；不要手改哈希或清单 |
| 提示WAL未合并 | 等待名称计算进程结束后重试，不要直接删除WAL文件 |
| 401 | Token失效或错误；重新检查账号并更新凭据 |
| 403 / 429 | 检查公开仓库权限、账号或组织策略及API限流；稍后重试 |
| fork尚未就绪 | GitHub创建fork是异步操作，等待后重试；无需手动安装Git |
| 上传或创建PR时超时 | 保留本地投稿状态，重试并检查返回链接；不要直接重复创建新批次 |
| PR已创建但CI等待授权 | 上游可能要求维护者批准首次贡献者的工作流；等待维护者处理 |
| 超过10000条 | 按类型或目标范围分批运行后分别准备，不会自动截断 |
| 投稿失败 | 本地CSV/CDB仍有效；修复网络或权限后手动重新预览 |

公开fork的工作流可能需要维护者批准，Token权限不能替代这项批准。[GitHub官方工作流授权说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks)

## 本版验证范围

贡献证据读取、HTTP/API权限边界、凭据与桥接、排重、fork/分支/提交/PR、失败重试使用合成数据和fake GitHub验证。真实网络验证只读，不为软件验收创建真实findings PR；fake写入通过不代表真实账号已获得权限或维护者已批准合并。

完整源码回归、NativeAOT前端、凭据遮蔽、控件居中、EXE安装及各项最终结果见[2.4.0发行验证附件](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.4.0/CODNameFinder-2.4.0-validation.json)。历史研究与2.3.0关联算法适配见[原版本发布记录](release-2.3.0.zh-CN.md)。
