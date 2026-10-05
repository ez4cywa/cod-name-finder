using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform;
using Avalonia.VisualTree;
using Fluid.Avalonia.Acrylic;
using SkiaSharp;
using System.Text.Json.Serialization;

namespace CODNameFinder.App;

/// <summary>One rendering boundary for glass, its readable fallback and diagnostics.</summary>
internal static class GlassEffects
{
    private static bool? _available;
    private static int _validatedShaders;
    // Shared by the actual material and diagnostics so packaged builds can report their rendering policy.
    private const double BlurRadius = 4;
    private const double Vibrancy = 1.25;
    private const double RefractionHeight = 12;
    private const double RefractionAmount = 22;
    private const bool ChromaticAberration = true;
    private const bool DepthEffect = true;

    internal static bool Available => _available ??= CheckShaders();

    private static bool CheckShaders()
    {
        if (Environment.GetCommandLineArgs().Contains("--reduced-effects")) return false;
        // Compile the exact bundled shaders before adding any custom draw operation.
        // SKRuntimeEffect compiles native Skia shader code and works with .NET NativeAOT.
        try
        {
            foreach (var name in new[] { "AcrylicShader", "AcrylicHighlight", "AcrylicGamma",
                         "AcrylicInteractiveHighlight", "AcrylicProgressiveMask", "AcrylicBackdropTransform" })
            {
                using var stream = AssetLoader.Open(new Uri($"avares://Fluid.Avalonia.Acrylic/Assets/Shaders/{name}.sksl"));
                using var reader = new StreamReader(stream);
                using var effect = SKRuntimeEffect.CreateShader(reader.ReadToEnd(), out _);
                if (effect is null) return false;
                _validatedShaders++;
            }
            return true;
        }
        catch (Exception) { return false; }
    }

    internal static Control Surface(Control content, Thickness padding, double radius, bool strong)
    {
        if (!Available)
            return new Border { Child = content, Padding = padding, CornerRadius = new CornerRadius(radius),
                Background = new SolidColorBrush(Color.Parse(strong ? "#F01B2638" : "#ED1A2435")) };
        return new AcrylicSurface
        {
            // Fluid's default template does not forward ContentControl.Padding.
            Content = new Border { Child = content, Padding = padding }, CornerRadius = new CornerRadius(radius),
            HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch,
            BlurRadius = BlurRadius, Vibrancy = Vibrancy, Brightness = 0.025,
            TintColor = Color.Parse("#0DADC4DD"),
            SurfaceColor = Color.Parse(strong ? "#68192230" : "#4C182230"),
            RefractionHeight = RefractionHeight, RefractionAmount = RefractionAmount, DepthEffect = DepthEffect,
            HighlightEnabled = true, HighlightWidth = 0.75, HighlightBlurRadius = 0.4,
            HighlightOpacity = 0.5, HighlightAngle = 55, HighlightFalloff = 1.1,
            ChromaticAberration = ChromaticAberration, AdaptiveLuminanceEnabled = false,
            RevealBorderEnabled = false, ShadowEnabled = false
        };
    }

    internal static GlassRenderingState Snapshot(Visual visual)
    {
        var counts = AcrylicDiagnostics.Snapshot;
        return new GlassRenderingState
        {
            EffectsEnabled = Available, ValidatedShaders = _validatedShaders,
            ShaderPanels = visual.GetVisualDescendants().OfType<AcrylicSurface>().Count(),
            CapturesPublished = counts.CapturesPublished, RendererInvalidations = counts.RendererInvalidations,
            FilterCacheMisses = counts.FilterCacheMisses, FilterCacheHits = counts.FilterCacheHits,
            GpuFilterSurfaces = counts.FilterGpuSurfaces, CpuFilterSurfaces = counts.FilterCpuSurfaces,
            FilterFailures = counts.FilterSurfaceFailures,
            BlurRadius = BlurRadius, Vibrancy = Vibrancy, RefractionHeight = RefractionHeight,
            RefractionAmount = RefractionAmount, ChromaticAberration = ChromaticAberration, DepthEffect = DepthEffect
        };
    }
}

internal sealed class GlassRenderingState
{
    [JsonPropertyName("effects_enabled")] public bool EffectsEnabled { get; set; }
    [JsonPropertyName("validated_shaders")] public int ValidatedShaders { get; set; }
    [JsonPropertyName("shader_panels")] public int ShaderPanels { get; set; }
    [JsonPropertyName("captures_published")] public long CapturesPublished { get; set; }
    [JsonPropertyName("renderer_invalidations")] public long RendererInvalidations { get; set; }
    [JsonPropertyName("filter_cache_misses")] public long FilterCacheMisses { get; set; }
    [JsonPropertyName("filter_cache_hits")] public long FilterCacheHits { get; set; }
    [JsonPropertyName("gpu_filter_surfaces")] public long GpuFilterSurfaces { get; set; }
    [JsonPropertyName("cpu_filter_surfaces")] public long CpuFilterSurfaces { get; set; }
    [JsonPropertyName("filter_failures")] public long FilterFailures { get; set; }
    [JsonPropertyName("blur_radius")] public double BlurRadius { get; set; }
    [JsonPropertyName("vibrancy")] public double Vibrancy { get; set; }
    [JsonPropertyName("refraction_height")] public double RefractionHeight { get; set; }
    [JsonPropertyName("refraction_amount")] public double RefractionAmount { get; set; }
    [JsonPropertyName("chromatic_aberration")] public bool ChromaticAberration { get; set; }
    [JsonPropertyName("depth_effect")] public bool DepthEffect { get; set; }
    [JsonPropertyName("style_reference")] public string StyleReference { get; set; } = "KaranocaVe/LiquidGlassAvaloniaUI";
    [JsonPropertyName("backdrop_palette")] public string BackdropPalette { get; set; } = "blue-rose-amber-original-vector";
}
