# Windows 开发与构建指南

本页面向开发者，当前目标版本2.3.0，最终验证报告随发行附件提供。普通用户下载 [2.3.0 安装包](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.3.0/CODNameFinder-2.3.0-Setup.exe) 后即可使用，无需安装本页的编译工具；操作步骤见[使用教程](user-guide.zh-CN.md)。构建目标为 Windows 11 x64，界面使用 Avalonia NativeAOT，文件处理由随包的 Python worker 完成，匹配引擎使用 Rust CPU 和可选 OpenCL GPU。

## 构建依赖

| 组件 | 仓库要求与沿用的构建环境 |
| --- | --- |
| Python | `pyproject.toml` 声明 `>=3.11`；已验证的 2.2.1 打包机使用 CPython 3.14.0 x64。发布复现建议使用该版本和 `requirements.lock.txt`；其他 Python 版本未获得相同打包验证。 |
| Python 包 | `requirements.lock.txt` 固定 PyInstaller、NumPy、PyOpenCL、LZ4、pytest 等版本。PySide6 仅用于保留的旧 GUI 和测试，正式 Avalonia 安装包排除了 PySide6/Qt。 |
| .NET SDK | `dotnet/global.json` 固定 10.0.112，允许同功能带的较新补丁；从 `dotnet` 目录运行能使用该 SDK 选择。 |
| Avalonia/NuGet | App 使用 Avalonia 12.1.3、Fluid.Avalonia.Acrylic 1.4.0，各项目的 `packages.lock.json` 固定依赖，恢复使用 `--locked-mode`。 |
| NativeAOT C++ 工具链 | 安装 Visual Studio Build Tools 的“使用 C++ 的桌面开发”工作负载，以及 MSVC x64 编译工具和 Windows SDK。常规托管构建成功不能替代 NativeAOT 发布检查。 |
| Rust | 安装 Windows x64 MSVC 工具链；已验证的 2.2.1 构建机使用 rustc/cargo 1.96.0。依赖由 `native/Cargo.lock` 固定，使用 `cargo build --locked`。 |
| Inno Setup | 已验证的 2.2.1 使用 Inno Setup 6.7.3。`scripts/build_installer.py` 接受 `INNO_ISCC` 指向 `ISCC.exe`，也查找 PATH 和常见安装位置。编译器未随源码分发。 |
| PowerShell | 日常命令可使用 Windows PowerShell；`scripts/validate-capture-frontend.ps1` 明确要求 PowerShell 7。 |
| GPU 验证 | OpenCL 由显卡驱动提供，项目不捆绑驱动。CPU 构建和计算不要求有 GPU，但完整安装器验收包含 GPU 路径，须有可用 OpenCL 设备。 |
| 安装器验收辅助包 | `scripts/validate_installer.py` 另导入 `pefile` 和 `Pillow`；`requirements-verify.txt` 固定 pefile 2024.8.26、Pillow 12.2.0，它们不属于用户运行依赖。 |

首次安装依赖及恢复工具会访问对应包源。名称计算的离线运行方式与开发依赖下载是不同流程。

## 准备源码

以下在 PowerShell 中执行。路径仅为示例，可以替换为自己的源码目录。

```powershell
git clone https://github.com/ez4cywa/cod-name-finder.git
Set-Location cod-name-finder
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock.txt -r requirements-verify.txt
```

如果本机策略阻止虚拟环境激活，可直接用 `.\.venv\Scripts\python.exe` 替代后续的 `python`。安装包打包时以当前 Python 解释器作为 worker 的运行时来源。

## 构建与测试

在仓库根目录运行：

```powershell
python scripts/generate_hash_registry.py --check
cargo build --locked --release --manifest-path native/Cargo.toml
python -m pytest -q

Push-Location dotnet
dotnet restore CODNameFinder.App/CODNameFinder.App.csproj --locked-mode
dotnet build CODNameFinder.App/CODNameFinder.App.csproj -c Release --no-restore
Pop-Location
```

`--check` 验证注册表生成文件未漂移。修改 `docs/hash-registry.json` 后，先运行不带 `--check` 的生成命令并审阅变更，再执行检查。Rust 构建生成 `native/target/release/finder_native.dll` 和独立 CDB 检查器。pytest 使用小样本和合成内存测试，不要求提供游戏、研究项目或 Cordycep。

Python 后端可通过 `python -m finder --help` 查看命令。正式一键计算配置实例和各命令参数见[教程中的命令行部分](user-guide.zh-CN.md#安装版命令行无需-python-或-git)。源码调试的 GUI 通过 `COD_NAME_FINDER_ENGINE` 指向一个已经打包的 worker，例如：

```powershell
$env:COD_NAME_FINDER_ENGINE = (Resolve-Path .\dist\2.3.0\CODNameFinder\engine\NameFinder.Engine.exe).Path
Push-Location dotnet
dotnet run --project CODNameFinder.App/CODNameFinder.App.csproj -c Release --no-build
Pop-Location
```

该示例要求先完成下面的完整发布构建。单独 `dotnet build` 不会创建 Python worker；不要把 `COD_NAME_FINDER_ENGINE` 指向 `python.exe`。托管调试下 `selftest` 可以检查 Core 行为，但输出的 `native_aot` 只有真正 NativeAOT EXE 才会为 `true`。

## 生成 EXE 安装包

先关闭正在运行的构建输出，确认没有进程占用 `dist/2.3.0/CODNameFinder`。如果 Inno Setup 不在常见位置，设置：

```powershell
$env:INNO_ISCC = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
python scripts/build_release.py
```

脚本按顺序检查注册表、构建 Rust、运行 pytest、发布 Avalonia NativeAOT、用 PyInstaller 打包 worker、复制教程/资源和许可说明，最后编译安装器并输出 SHA256。脚本会重新创建本版本的分发目录；发现文件仍被进程占用时会先失败，要求关闭程序后重试。完整输出主要为：

| 路径 | 内容 |
| --- | --- |
| `dist/2.3.0/CODNameFinder/` | 完整安装负载：主程序、`engine`、教程、示例、资源及许可。 |
| `releases/CODNameFinder-2.3.0-Setup.exe` | Windows EXE 安装包。 |
| `releases/CODNameFinder-2.3.0-source.zip` | 当前脚本生成的源码归档。 |
| `releases/SHA256SUMS.txt` | 安装包和源码归档校验值。 |
| `releases/release.json` | 构建清单；其 `publication` 记录本地构建，不代替 GitHub 发布状态。 |

主程序依赖完整负载，不能只发一个 `CODNameFinder.exe`。安装器按当前用户安装，不要求系统上另装 Python 或 .NET。公开 GitHub Release 应选择经过验收的安装包，并核对归档、校验文件与同一版本源码一致；公开过程中更新的文档可以来自 GitHub 对应标签的源码归档。

## 验收发布包

完成构建后运行：

```powershell
.\dist\2.3.0\CODNameFinder\CODNameFinder.exe selftest
pwsh -File scripts/validate-capture-frontend.ps1 -App .\dist\2.3.0\CODNameFinder\CODNameFinder.exe
python scripts/validate_installer.py
```

第一项应输出 15 项 Core 检查及 `native_aot: true`。第二项使用合成桥接后端验证 BAT 选择、参数传递、捕获完成和停止行为，不启动真实游戏加载器。第三项以独立验证 AppId 安装到临时目录，在 System32-only PATH 和缺失系统 .NET 运行时的环境验证内置 worker、CPU/GPU、示例、快照、CDB 增量、教程、界面与卸载。验收日志写入本地 `validation`，不属于公开数据。

2.3.0源码回归通过741项pytest，注册表`--check`及变更格式检查通过。最终EXE安装验收、NativeAOT自检和逐项状态以[CODNameFinder-2.3.0-validation.json发行附件](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.3.0/CODNameFinder-2.3.0-validation.json)为准，范围见[本版发布说明](release-2.3.0.zh-CN.md)。2.2.1 本地版的524项pytest、15项Core检查及2.2.2的[历史公开验收](release-2.2.2.zh-CN.md)继续保留，不能代替新版本验收。MW7 Beta 的真实 BAT 启动与捕获属于2026-10-05的现场记录，BO7 的现场捕获尚未通过，Saluki GUI 的现场加载尚未验证。改变加载器、配置、游戏模块或显卡驱动后，必须重新验证相应行为，不能沿用原机器的现场结论。

## 修改2.3.0关联推测规则

本次上游核对固定在 `dbe25197cee05b8315b4effff1841ed4868152f0`；PR、独立实现和实际输入验证详见[更新记录](upstream-update-20261009.zh-CN.md)。开发修改应保持以下接口与约束：

| 代码 | 职责与约束 |
|---|---|
| `finder/snapshot.py` | 现代CODIDS v1强制同名池清单，以type名识别捕获池，核对game／count／sort；不得将63位alias提升为满64位目标 |
| `finder/spellings.py` | `resolve_table_spelling()` 只接受通过原source-table完整键验证的有限恢复拼写，不创建证据或排除键 |
| `finder/soundplans.py` | `build_sound_plans()` 生成重复namespace、alias缺失文件族候选；target模板来自同类型完整键，donor不改变target存在性；双方可用时为namespace预留至多四分之一额度，余量按游标返还 |
| `finder/soundbyte.py` | `build_final_byte_plans()` 返回plans与准备报告；FNV63／64模环内反求最后ASCII字节；先合并profile归一化等价前缀，字节运算与桶探测同受准备上限约束 |
| `finder/typedplans.py` | `build_typed_plans(source_names_by_kind, target_names_by_kind, target_kinds)` 保持动画／alias、整词武器身份／图片／材质的类型关系；武器身份来自已核验动画、图片、材质或alias，不直接假设weapon类型输入 |
| `finder/pipeline.py` | 统一估算和执行准备，按类型、profile和当前目标键确认目标模板；新规则受`cross_asset`控制 |
| `finder/methods.py`、`finder/completedcache.py` | 新生成器及其依赖源码进入方法身份和完整缓存指纹；改变规则后旧缓存不能绕过新代码 |
| `scripts/build_release.py` | worker内保留计算生成器和校验源码资源，教程与本版说明随完整EXE安装负载提供 |

源音频表的恢复拼写只能证明供体种子在原表规则下成立，不能代替当前目标的独立匹配。无键TXT或文件名可作候选，只有在当前同类型目标完整键上回算通过后，才能进入目标惯例学习。命中后仍走冲突剔除、Saluki完整键／原样名称排除和CDB回读。

新增生成器测试应包含输入中没有的新名称、wrong kind／wrong profile拒绝、borrowed或unkeyed线索隔离、反斜杠与编码尾、绑定take元组、有限预算、取消及缓存源码变化。上游公开快照只读检查与合成单元测试分别记录；公开9,513,578条记录的导入成功不等于跑完该空间的名称计算。不要将上游吞吐或历史本机速度填作本版新算法实测。

## 数据与许可

构建不要求提供研究数据库、游戏文件、Saluki 索引或 Cordycep。现场捕获需使用者自行提供兼容加载器和游戏；完整快照及名称索引是用户本地数据，不能因构建脚本存在就上传到公开仓库。公开源码遵循 [MIT](../LICENSE)，第三方组件和参考文件按[第三方说明](../THIRD_PARTY_NOTICES.md)保留许可。
