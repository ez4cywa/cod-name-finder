using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Controls.Chrome;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using Avalonia.VisualTree;

namespace CODNameFinder.App;

/// <summary>A compact client titlebar using the same glass surface as the working panels.</summary>
internal sealed class GlassWindowChrome
{
    public Control Surface { get; }
    public TextBlock Title { get; }
    public Button Help { get; }
    public Button Minimize { get; }
    public Button Maximize { get; }
    public Button Close { get; }

    public GlassWindowChrome(Window window, Action openTutorial)
    {
        // Avalonia 12 keeps the native resize frame without drawing a native titlebar.
        window.ExtendClientAreaToDecorationsHint = true;
        window.ExtendClientAreaTitleBarHeightHint = 0;
        window.WindowDecorations = WindowDecorations.BorderOnly;
        window.CanResize = true;

        var toolbar = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto"),
            ColumnSpacing = 12,
            Height = 36
        };
        var dragArea = new Border { Background = Brushes.Transparent };
        var identity = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 10,
            VerticalAlignment = VerticalAlignment.Center,
            IsHitTestVisible = false
        };
        using (var stream = AssetLoader.Open(new Uri("avares://CODNameFinder/Assets/cod-name-finder.png")))
        {
            var icon = new Image { Source = new Bitmap(stream), Width = 24, Height = 24 };
            AutomationProperties.SetName(icon, "COD Name Finder 软件图标");
            identity.Children.Add(icon);
        }
        Title = new TextBlock
        {
            Text = "COD Name Finder",
            FontSize = 14,
            FontWeight = FontWeight.SemiBold,
            TextTrimming = TextTrimming.CharacterEllipsis,
            VerticalAlignment = VerticalAlignment.Center
        };
        identity.Children.Add(Title);
        dragArea.Child = identity;
        // Only this empty/title region moves the window. Help and caption buttons are siblings.
        WindowDecorationProperties.SetElementRole(dragArea, WindowDecorationsElementRole.User);
        dragArea.PointerPressed += (_, args) =>
        {
            if (!args.GetCurrentPoint(dragArea).Properties.IsLeftButtonPressed) return;
            if (args.ClickCount == 2)
            {
                if (window.CanMaximize)
                    window.WindowState = window.WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
            }
            else window.BeginMoveDrag(args);
            args.Handled = true;
        };
        toolbar.Children.Add(dragArea);

        Help = new Button
        {
            Content = "使用教程 · F1", MinHeight = 32, Height = 32,
            Padding = new Thickness(12, 4), VerticalAlignment = VerticalAlignment.Center,
            HorizontalContentAlignment = HorizontalAlignment.Center,
            CornerRadius = new CornerRadius(11)
        };
        AutomationProperties.SetName(Help, "打开软件使用教程，快捷键 F1");
        WindowDecorationProperties.SetElementRole(Help, WindowDecorationsElementRole.User);
        Help.Click += (_, _) => openTutorial();
        Grid.SetColumn(Help, 1); toolbar.Children.Add(Help);

        var captions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, VerticalAlignment = VerticalAlignment.Center };
        Minimize = Caption("最小化窗口", "M 1,5.5 L 11,5.5 L 11,6.5 L 1,6.5 Z");
        Maximize = Caption("最大化窗口", "M 1,1 L 11,1 L 11,11 L 1,11 Z");
        Close = Caption("关闭窗口", "M 1,1 L 11,11 M 11,1 L 1,11");
        Minimize.Click += (_, _) => window.WindowState = WindowState.Minimized;
        Maximize.Click += (_, _) => window.WindowState = window.WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
        // Close follows the ordinary Closing event, including the existing stop-and-save guard.
        Close.Click += (_, _) => window.Close();
        captions.Children.Add(Minimize); captions.Children.Add(Maximize); captions.Children.Add(Close);
        Grid.SetColumn(captions, 2); toolbar.Children.Add(captions);
        window.PropertyChanged += (_, args) =>
        {
            if (args.Property != Window.WindowStateProperty) return;
            var maximized = window.WindowState == WindowState.Maximized;
            AutomationProperties.SetName(Maximize, maximized ? "还原窗口" : "最大化窗口");
            ToolTip.SetTip(Maximize, maximized ? "还原" : "最大化");
            Maximize.Content = Glyph(maximized
                ? "M 3,1 L 11,1 L 11,9 M 1,3 L 9,3 L 9,11 L 1,11 Z"
                : "M 1,1 L 11,1 L 11,11 L 1,11 Z");
        };

        Surface = GlassTheme.Panel(toolbar, new Thickness(14, 6), radius: 18);
        Surface.Classes.Add("compact-titlebar");
        AutomationProperties.SetName(Surface, "玻璃窗口标题栏");
    }

    public string[] WindowButtonNames() => new[] { Minimize, Maximize, Close }
        .Where(button => button.IsVisible && button.Bounds.Width > 0)
        .Select(button => AutomationProperties.GetName(button) ?? "").ToArray();

    private static Button Caption(string name, string geometry)
    {
        var button = new Button
        {
            Content = Glyph(geometry), Width = 34, MinHeight = 32, Height = 32,
            Padding = new Thickness(8), CornerRadius = new CornerRadius(10),
            HorizontalContentAlignment = HorizontalAlignment.Center,
            VerticalContentAlignment = VerticalAlignment.Center
        };
        AutomationProperties.SetName(button, name);
        ToolTip.SetTip(button, name);
        WindowDecorationProperties.SetElementRole(button, WindowDecorationsElementRole.User);
        return button;
    }

    private static Control Glyph(string geometry) => new Avalonia.Controls.Shapes.Path
    {
        Data = Geometry.Parse(geometry), Width = 12, Height = 12,
        Stroke = GlassTheme.Text, StrokeThickness = 1.3,
        Stretch = Stretch.Uniform, IsHitTestVisible = false
    };
}
