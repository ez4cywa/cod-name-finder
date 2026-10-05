using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace CODNameFinder.App;

/// <summary>One material and backdrop definition shared by the main window and offline guide.</summary>
public static class GlassTheme
{
    public static readonly IBrush Text = Brush.Parse("#F4F7FF");
    public static readonly IBrush Secondary = Brush.Parse("#C4D0E3");
    public static readonly IBrush Line = Brush.Parse("#526C86A0");
    public static readonly IBrush Accent = Brush.Parse("#B4E9FF");

    public static void ConfigureWindow(Window window)
    {
        window.TransparencyLevelHint = [WindowTransparencyLevel.Mica, WindowTransparencyLevel.AcrylicBlur, WindowTransparencyLevel.None];
        window.TransparencyBackgroundFallback = Brush.Parse("#10131D");
        window.Background = Brushes.Transparent;
    }

    public static Control Backdrop(Control content)
    {
        var backdrop = new Grid
        {
            ClipToBounds = true,
            Background = Gradient("#FF0C1322", "#FF14182C", "#FF13121C", new RelativePoint(0, 0, RelativeUnit.Relative), new RelativePoint(1, 1, RelativeUnit.Relative))
        };
        // Original vector light field: no external wallpaper or moving background.
        // The curved bands give the lens edges something to refract at every window size.
        backdrop.Children.Add(Glow("#A80091FF", 870, 750, HorizontalAlignment.Left, VerticalAlignment.Top, new Thickness(-360, -340, 0, 0)));
        backdrop.Children.Add(Glow("#72FF247B", 800, 920, HorizontalAlignment.Right, VerticalAlignment.Center, new Thickness(0, 40, -460, 0)));
        backdrop.Children.Add(Glow("#87FF9B42", 940, 640, HorizontalAlignment.Left, VerticalAlignment.Bottom, new Thickness(-300, 0, 0, -370)));
        backdrop.Children.Add(Glow("#416DB8FF", 720, 620, HorizontalAlignment.Right, VerticalAlignment.Bottom, new Thickness(0, 0, -300, -310)));
        backdrop.Children.Add(LightBands());
        backdrop.Children.Add(new Border
        {
            IsHitTestVisible = false,
            Background = new RadialGradientBrush
            {
                Center = new RelativePoint(0.48, 0.35, RelativeUnit.Relative),
                GradientOrigin = new RelativePoint(0.48, 0.35, RelativeUnit.Relative),
                RadiusX = new RelativeScalar(0.95, RelativeUnit.Relative),
                RadiusY = new RelativeScalar(0.95, RelativeUnit.Relative),
                GradientStops = new GradientStops { new(Color.Parse("#00000000"), 0), new(Color.Parse("#61070A10"), 1) }
            }
        });
        backdrop.Children.Add(content);
        return backdrop;
    }

    public static Control Panel(Control content, Thickness padding, double radius = 22, bool strong = false)
    {
        var layers = new Grid();
        var shell = new Border
        {
            Child = layers,
            CornerRadius = new CornerRadius(radius),
            BorderThickness = new Thickness(1),
            BorderBrush = Gradient("#BCE5F3FF", "#364A607A", "#766B739A", new RelativePoint(0, 0, RelativeUnit.Relative), new RelativePoint(1, 1, RelativeUnit.Relative)),
            Background = Brushes.Transparent,
            BoxShadow = BoxShadows.Parse("0 12 30 0 #5003060D")
        };
        shell.Classes.Add("glass-panel");
        layers.Children.Add(GlassEffects.Surface(content, padding, radius - 1, strong));
        layers.Children.Add(new Border
        {
            IsHitTestVisible = false,
            CornerRadius = new CornerRadius(radius - 1),
            Background = Gradient("#13F0F8FF", "#02458ABC", "#00DAA4C0", new RelativePoint(0, 0, RelativeUnit.Relative), new RelativePoint(0.7, 1, RelativeUnit.Relative))
        });
        return shell;
    }

    public static Border Badge(string text)
    {
        var label = new TextBlock { Text = text, FontSize = 12, Foreground = Secondary, VerticalAlignment = VerticalAlignment.Center };
        return new Border { Child = label, Padding = new Thickness(10, 4), CornerRadius = new CornerRadius(12), Background = Brush.Parse("#60131E2E"), BorderBrush = Brush.Parse("#587992A9"), BorderThickness = new Thickness(1), VerticalAlignment = VerticalAlignment.Center };
    }

    private static LinearGradientBrush Gradient(string first, string middle, string last, RelativePoint start, RelativePoint end) => new()
    {
        StartPoint = start, EndPoint = end,
        GradientStops = new GradientStops { new(Color.Parse(first), 0), new(Color.Parse(middle), 0.52), new(Color.Parse(last), 1) }
    };

    private static Control LightBands()
    {
        var canvas = new Canvas { Width = 1060, Height = 850, IsHitTestVisible = false };
        canvas.Children.Add(new Avalonia.Controls.Shapes.Path
        {
            Data = Geometry.Parse("M -140,430 C 180,420 200,-55 505,-60 C 700,-60 890,70 1180,-35"),
            Stroke = Gradient("#006FBFFF", "#286FBFFF", "#08FFC3E0", new RelativePoint(0, 1, RelativeUnit.Relative), new RelativePoint(1, 0, RelativeUnit.Relative)),
            StrokeThickness = 36
        });
        canvas.Children.Add(new Avalonia.Controls.Shapes.Path
        {
            Data = Geometry.Parse("M 80,980 C 350,530 720,970 1160,360"),
            Stroke = Gradient("#00FFD7AE", "#28FFC39A", "#16FD7FA9", new RelativePoint(0, 1, RelativeUnit.Relative), new RelativePoint(1, 0, RelativeUnit.Relative)),
            StrokeThickness = 58
        });
        return new Viewbox { Child = canvas, Stretch = Stretch.Fill, IsHitTestVisible = false };
    }

    private static Border Glow(string color, double width, double height, HorizontalAlignment horizontal, VerticalAlignment vertical, Thickness margin)
    {
        var light = Color.Parse(color);
        return new Border
        {
            Width = width, Height = height, HorizontalAlignment = horizontal, VerticalAlignment = vertical, Margin = margin, IsHitTestVisible = false,
            Background = new RadialGradientBrush
            {
                GradientStops = new GradientStops { new(light, 0), new(Color.FromArgb(0, light.R, light.G, light.B), 1) }
            }
        };
    }
}
