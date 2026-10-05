# Windows 开发与构建指南

本页面向开发者。普通用户下载 [2.2.2 安装包](https://github.com/ez4cywa/cod-name-finder/releases/download/v2.2.2/CODNameFinder-2.2.2-Setup.exe) 后可直接使用，无需安装本页的编译工具；操作步骤见[使用教程](user-guide.zh-CN.md)。构建目标为 Windows 11 x64，界面使用 Avalonia NativeAOT，文件处理由随包的 Python worker 完成，匹配引擎使用 Rust CPU 和可选 OpenCL GPU。

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
$env:COD_NAME_FINDER_ENGINE = (Resolve-Path .\dist\2.2.2\CODNameFinder\engine\NameFinder.Engine.exe).Path
Push-Location dotnet
dotnet run --project CODNameFinder.App/CODNameFinder.App.csproj -c Release --no-build
Pop-Location
```

该示例要求先完成下面的完整发布构建。单独 `dotnet build` 不会创建 Python worker；不要把 `COD_NAME_FINDER_ENGINE` 指向 `python.exe`。托管调试下 `selftest` 可以检查 Core 行为，但输出的 `native_aot` 只有真正 NativeAOT EXE 才会为 `true`。

## 生成 EXE 安装包

先关闭正在运行的构建输出，确认没有进程占用 `dist/2.2.2/CODNameFinder`。如果 Inno Setup 不在常见位置，设置：

```powershell
$env:INNO_ISCC = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
python scripts/build_release.py
```

脚本按顺序检查注册表、构建 Rust、运行 pytest、发布 Avalonia NativeAOT、用 PyInstaller 打包 worker、复制教程/资源和许可说明，最后编译安装器并输出 SHA256。脚本会重新创建本版本的分发目录；发现文件仍被进程占用时会先失败，要求关闭程序后重试。完整输出主要为：

| 路径 | 内容 |
| --- | --- |
| `dist/2.2.2/CODNameFinder/` | 完整安装负载：主程序、`engine`、教程、示例、资源及许可。 |
| `releases/CODNameFinder-2.2.2-Setup.exe` | Windows EXE 安装包。 |
| `releases/CODNameFinder-2.2.2-source.zip` | 当前脚本生成的源码归档。 |
| `releases/SHA256SUMS.txt` | 安装包和源码归档校验值。 |
| `releases/release.json` | 构建清单；其 `publication` 记录本地构建，不代替 GitHub 发布状态。 |

主程序依赖完整负载，不能只发一个 `CODNameFinder.exe`。安装器按当前用户安装，不要求系统上另装 Python 或 .NET。公开 GitHub Release 应选择经过验收的安装包，并核对归档、校验文件与同一版本源码一致；公开过程中更新的文档可以来自 GitHub 对应标签的源码归档。

## 验收发布包

完成构建后运行：

```powershell
.\dist\2.2.2\CODNameFinder\CODNameFinder.exe selftest
pwsh -File scripts/validate-capture-frontend.ps1 -App .\dist\2.2.2\CODNameFinder\CODNameFinder.exe
python scripts/validate_installer.py
```

第一项应输出 15 项 Core 检查及 `native_aot: true`。第二项使用合成桥接后端验证 BAT 选择、参数传递、捕获完成和停止行为，不启动真实游戏加载器。第三项以独立验证 AppId 安装到临时目录，在 System32-only PATH 和缺失系统 .NET 运行时的环境验证内置 worker、CPU/GPU、示例、快照、CDB 增量、教程、界面与卸载。验收日志写入本地 `validation`，不属于公开数据。

2.2.1 本地版的历史记录为 524 项 pytest、15 项 Core 检查及安装器验收通过；2.2.2 公开版的最终验证范围见[发布说明](release-2.2.2.zh-CN.md)。MW7 Beta 的真实 BAT 启动与捕获已通过，BO7 的现场捕获尚未通过，Saluki GUI 的现场加载尚未验证。改变加载器、配置、游戏模块或显卡驱动后，必须重新验证相应行为，不能沿用原机器的现场结论。

## 数据与许可

构建不要求提供研究数据库、游戏文件、Saluki 索引或 Cordycep。现场捕获需使用者自行提供兼容加载器和游戏；完整快照及名称索引是用户本地数据，不能因构建脚本存在就上传到公开仓库。公开源码遵循 [MIT](../LICENSE)，第三方组件和参考文件按[第三方说明](../THIRD_PARTY_NOTICES.md)保留许可。
