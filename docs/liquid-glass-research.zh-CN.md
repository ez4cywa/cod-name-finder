# 液态玻璃 UI 依赖研究

## 2.2.2 视觉适配

2026-10-05 按 [KaranocaVe/LiquidGlassAvaloniaUI](https://github.com/KaranocaVe/LiquidGlassAvaloniaUI) 的 Demo 与截图生成器调整界面：原创蓝、玫红、暖橙背景光场和弯曲光带，较透明的表面、圆角透镜折射、边缘高光及轻阴影。继续使用保留原作者许可的 Fluid 维护分支，渲染由实际 Skia shader 完成。

实际玻璃参数为 `BlurRadius=4`、`Vibrancy=1.25`、`RefractionHeight=12`、`RefractionAmount=22`，启用 depth 与 chromatic aberration，边缘高光透明度 0.5。原项目 README 的夸张演示参数用于展示效果，本工具按文本密度降低强度。输入和下拉菜单保持暗色可读底，关闭特效时提供近不透明的降级表面。

主窗口去掉大型软件介绍卡片，使用紧凑玻璃标题栏保留应用识别、F1 教程和窗口操作；窗口顶部与工具面板使用同一材质。下方保留原依赖研究记录，其中的最小示例参数是当时的探针，不代表当前应用参数。

核验日期：2026-10-02。研究只改本文，参考源码和隔离 API 探针保存在 `validation/glass-reference/`，未修改应用、NuGet 锁文件或 Python 引擎。

## 推荐依赖

采用 [Fluid.Avalonia.Acrylic 1.4.0](https://www.nuget.org/packages/Fluid.Avalonia.Acrylic/1.4.0)。直接读取 NuGet v3 包和 nuspec，目标框架为 net8.0，最低依赖 Avalonia 与 Avalonia.Skia 12.1.2；本软件 net10.0 / Avalonia 12.1.3 可以引用它。包内源码定位为 commit `013590eaa93666d368d775efdb3d7715591a4232`。SkiaSharp 由 Avalonia.Skia 传递提供，避免另行锁定不匹配的 SkiaSharp。

参考 [KaranocaVe/LiquidGlassAvaloniaUI](https://github.com/KaranocaVe/LiquidGlassAvaloniaUI/tree/cde864d6efebc5b32484eb055900308ef4f65754)，检查时 main 为 `cde864d6efebc5b32484eb055900308ef4f65754`，同名 NuGet flatcontainer 返回 404。它是效果设计来源；可直接发布引用的 Fluid 包是其派生项目。两者均 MIT；打包 Fluid 的 LICENSE，保留 KaranocaVe 2025 和 Alpaq92 2026 两条版权。

```xml
<PackageReference Include="Fluid.Avalonia.Acrylic" Version="1.4.0" />
```

```csharp
using Fluid.Avalonia.Acrylic;

AppBuilder.Configure<App>()
    .UsePlatformDetect()
    .UseAcrylicPerformanceDefaults(128L * 1024 * 1024, 8);
```

该扩展会替换先前的 CompositionOptions / SkiaOptions；自定义 `.With(...)` 应放在它之后。[实际启动扩展源码](https://github.com/Alpaq92/Fluid.Avalonia.Acrylic/blob/013590eaa93666d368d775efdb3d7715591a4232/Fluid.Avalonia.Acrylic/AcrylicAppBuilderExtensions.cs)

## 最小控件

```xml
xmlns:acrylic="using:Fluid.Avalonia.Acrylic"

<acrylic:AcrylicSurface CornerRadius="24"
                        BlurRadius="8"
                        Vibrancy="1.15"
                        TintColor="#30405D88"
                        SurfaceColor="#70303D59"
                        RefractionHeight="12"
                        RefractionAmount="10"
                        HighlightEnabled="True"
                        HighlightOpacity="0.35"
                        ShadowEnabled="False"
                        ChromaticAberration="False"
                        AdaptiveLuminanceEnabled="False"
                        RevealBorderEnabled="False">
    <Border Padding="20"><!-- 普通可读控件 --></Border>
</acrylic:AcrylicSurface>
```

以上属性均从 [AcrylicSurface.cs](https://github.com/Alpaq92/Fluid.Avalonia.Acrylic/blob/013590eaa93666d368d775efdb3d7715591a4232/Fluid.Avalonia.Acrylic/AcrylicSurface.cs) 确认。它是 ContentControl，默认模板已包含内容裁剪、高光层，无需主题 Include。给它有色而静止的应用背景，折射才能显现。这里处理的是应用内部背景，不等于 Windows 桌面模糊。

## NativeAOT 风险与验证

包未声明 IsAotCompatible。SKRuntimeEffect 编译 SkSL 在原生 Skia 内进行，不要求 .NET 动态代码，但背景捕获用了反射。[AcrylicBackdropProvider.cs](https://github.com/Alpaq92/Fluid.Avalonia.Acrylic/blob/013590eaa93666d368d775efdb3d7715591a4232/Fluid.Avalonia.Acrylic/AcrylicBackdropProvider.cs) 按名字查 TopLevel.Renderer、CompositingRenderer.SceneInvalidated 和 SceneInvalidatedEventArgs.DirtyRect。[AcrylicVisualRenderer.cs](https://github.com/Alpaq92/Fluid.Avalonia.Acrylic/blob/013590eaa93666d368d775efdb3d7715591a4232/Fluid.Avalonia.Acrylic/AcrylicVisualRenderer.cs) 查 ClipToBoundsRadius。隔离 managed API 探针确认 Renderer getter 和 CompositingRenderer 类型为 internal。

如采用原 NuGet 包，NativeAOT 发布需保留最小反射成员，并实测；下述根配置供实现验证，不能代替发布验收：

```xml
<linker>
  <assembly fullname="Avalonia.Controls">
    <type fullname="Avalonia.Controls.TopLevel"><property name="Renderer" /></type>
    <type fullname="Avalonia.Controls.Border"><property name="ClipToBoundsRadius" /></type>
  </assembly>
  <assembly fullname="Avalonia.Base">
    <type fullname="Avalonia.Rendering.Composition.CompositingRenderer"><event name="SceneInvalidated" /></type>
    <type fullname="Avalonia.Rendering.SceneInvalidatedEventArgs"><property name="DirtyRect" /></type>
  </assembly>
</linker>
```

项目项 `<TrimmerRootDescriptor Include="...xml" />` 引入它。根据应用实际控件补充圆角裁剪属性；避免为了省事保留整个 Avalonia 程序集。生产包必须证明 PE 没有 CLR directory，真实窗口中 shader 无加载错误，`AcrylicDiagnostics.Snapshot.CapturesPublished` / `FilterCacheMisses` 大于零；动态状态改变后 `RendererInvalidations` 增长。仅 `RuntimeFeature.IsDynamicCodeSupported=false` 不足以证明 AOT 发布。

## 性能和降级

保持两三块大玻璃面，输入框、下拉项、日志行用普通控件，底部操作固定且可读。背景静止，不加入常驻动画；关闭自适应亮度、色散和 pointer reveal，可减少快照和读回开销。默认背景捕获最短间隔 33 ms，有 dirty rect、像素 hash 和过滤缓存，但仍会在 UI 线程生成软件快照；玻璃 UI 的 GPU 与哈希引擎 OpenCL GPU 选择互不等价。

[AcrylicDrawOperation.cs](https://github.com/Alpaq92/Fluid.Avalonia.Acrylic/blob/013590eaa93666d368d775efdb3d7715591a4232/Fluid.Avalonia.Acrylic/AcrylicDrawOperation.cs) 显示：缺少 Skia lease 时跳过绘制，缺失快照时画薄白底，主 shader 加载失败时画红色错误面。库没有完整的产品级自动降级。应用应提供“减少特效 / 清晰界面”切换普通半透明或不透明 Border，并在低性能或 shader 失败时保留所有功能和文字对比度。降低 BlurRadius 到零仍保留捕获和 refraction，不能当作关闭特效。

## 隔离 NativeAOT 实测

独立项目 `validation/glass-native-probe/Glass.Native.Probe.csproj` 没有引用或还原产品项目。使用 net10.0 / Avalonia 12.1.3 / Fluid 1.4.0 和上述四项根配置，正常 `dotnet publish -c Release -r win-x64` 成功，生成 18,118,656 字节 x64 PE32+ EXE；CLR directory 为 `(0,0)`。

真实桌面窗口绘制静态渐变、青色斜条和一块 AcrylicSurface，首次截图后，三次改变背景、玻璃尺寸和窗口尺寸。运行退出 0，无 shader 加载错误或 MissingMetadata 异常。`RendererInvalidations` 从 1 增至 7、`CapturesPublished` 从 1 增至 4、`FilterCacheMisses` 从 2 增至 8、`DirtyRectAvailable` 从 1 增至 7；`FilterSurfaceFailures` 始终为 0。截图显示玻璃后的青色边界实际模糊，GPU 窗口和 CPU RenderTargetBitmap 自截图均产生 shader surface。

证据：`validation/glass-native-probe/results/report.json`、`results/initial.png` 和 `results/change-3.png`。发布默认输出 IL2104 汇总告警；设置 TrimmerSingleWarn=false 后，展开为一条 IL2075（SceneInvalidated 事件）、三条 IL2070（DirtyRect 属性、ClipToBoundsRadius 属性/属性枚举）。这些是第三方库按运行时类型反射缺少静态注解，根配置不能消除分析告警，但实测保留了所需成员。升级 Avalonia 或此包时必须复验，不应全局屏蔽所有 trimming 告警。生产软件完整布局和安装包仍需自己的验收。
