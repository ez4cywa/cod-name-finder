using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using CODNameFinder.Core;

namespace CODNameFinder.App;

/// <summary>Small offline Markdown renderer with no reflection or runtime plugin.</summary>
public sealed class TutorialWindow : Window
{
    public string MarkdownText { get; }

    public TutorialWindow()
    {
        Icon = App.LoadApplicationIcon();
        GlassTheme.ConfigureWindow(this);
        Title = "使用教程 · COD Name Finder " + AppVersion.Version; Width = 1000; Height = 760; MinWidth = 720; MinHeight = 500;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var path = Path.Combine(AppContext.BaseDirectory, "docs", "user-guide.zh-CN.md");
        MarkdownText = File.Exists(path) ? File.ReadAllText(path) : "# 教程缺失\n请重新安装完整的软件包，确保 docs/user-guide.zh-CN.md 与软件一起安装。";
        var document = new StackPanel { Spacing = 12, Margin = new Thickness(2, 0, 12, 8), MaxWidth = 1040, HorizontalAlignment = HorizontalAlignment.Stretch };
        RenderMarkdown(document, MarkdownText);
        var root = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto"), RowSpacing = 12, Margin = new Thickness(22, 18) };
        var heading = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 20 };
        var title = new TextBlock { Text = "使用教程", FontSize = 23, FontWeight = FontWeight.SemiBold, VerticalAlignment = VerticalAlignment.Center };
        heading.Children.Add(title); var guide = GlassTheme.Badge("离线阅读 · Esc 关闭"); Grid.SetColumn(guide, 1); heading.Children.Add(guide);
        root.Children.Add(GlassTheme.Panel(heading, new Thickness(18, 12), strong: true));
        var scroll = new ScrollViewer { Content = document, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        AutomationProperties.SetName(scroll, "软件使用教程内容");
        var readingPanel = GlassTheme.Panel(scroll, new Thickness(20, 16)); Grid.SetRow(readingPanel, 1); root.Children.Add(readingPanel);
        var footer = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 16 };
        var footerText = new TextBlock { Text = "首次使用：选择文件夹或完整快照 → 查看估算与 Saluki 差集 → 确认计算并导出。", Foreground = GlassTheme.Secondary, FontSize = 12, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(4, 0), TextWrapping = TextWrapping.Wrap };
        footer.Children.Add(footerText);
        var close = new Button { Content = "关闭教程", HorizontalAlignment = HorizontalAlignment.Right, MinHeight = 38 }; close.Click += (_, _) => Close();
        AutomationProperties.SetName(close, "关闭使用教程，快捷键 Esc"); Grid.SetColumn(close, 1); footer.Children.Add(close);
        Grid.SetRow(footer, 2); root.Children.Add(footer); Content = GlassTheme.Backdrop(root);
        KeyDown += (_, args) => { if (args.Key == Key.Escape) { Close(); args.Handled = true; } };
    }

    private static SelectableTextBlock Paragraph(string text) => new() { Text = Inline(text), TextWrapping = TextWrapping.Wrap, FontSize = 14, LineHeight = 24, Foreground = GlassTheme.Secondary };
    private static string Inline(string text) => text.Replace("`", "", StringComparison.Ordinal).Replace("**", "", StringComparison.Ordinal);
    private static void RenderMarkdown(StackPanel document, string markdown)
    {
        var lines = markdown.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n');
        for (var index = 0; index < lines.Length; index++)
        {
            var line = lines[index]; if (string.IsNullOrWhiteSpace(line)) continue;
            if (line.StartsWith("```", StringComparison.Ordinal))
            {
                var code = new List<string>();
                while (++index < lines.Length && !lines[index].StartsWith("```", StringComparison.Ordinal)) code.Add(lines[index]);
                document.Children.Add(new TextBox { Text = string.Join(Environment.NewLine, code), IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, FontFamily = new FontFamily("Consolas, Microsoft YaHei UI"), Padding = new Thickness(14, 10), Background = Brush.Parse("#A509172A"), BorderBrush = GlassTheme.Line, CornerRadius = new CornerRadius(12), Foreground = GlassTheme.Text });
            }
            else if (line.StartsWith('|'))
            {
                var rows = new List<string[]>();
                while (index < lines.Length && lines[index].StartsWith('|'))
                {
                    var cells = lines[index].Trim().Trim('|').Split('|').Select(cell => cell.Trim()).ToArray();
                    if (!cells.All(cell => cell.Length > 0 && cell.All(character => character is '-' or ':'))) rows.Add(cells);
                    index++;
                }
                index--;
                if (rows.Count > 0) document.Children.Add(Table(rows));
            }
            else if (line.StartsWith('#'))
            {
                var level = line.TakeWhile(character => character == '#').Count();
                document.Children.Add(new SelectableTextBlock { Text = line[level..].Trim(), TextWrapping = TextWrapping.Wrap, FontWeight = FontWeight.SemiBold, FontSize = level == 1 ? 24 : level == 2 ? 19 : 16, Margin = new Thickness(0, level == 1 ? 0 : 12, 0, 2), Foreground = level == 1 ? GlassTheme.Accent : GlassTheme.Text });
            }
            else document.Children.Add(Paragraph(line));
        }
    }
    private static Grid Table(List<string[]> rows)
    {
        var columns = rows.Max(row => row.Length);
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions(string.Join(',', Enumerable.Repeat("*", columns))) };
        for (var row = 0; row < rows.Count; row++)
        {
            grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            for (var column = 0; column < rows[row].Length; column++)
            {
                var text = Paragraph(rows[row][column]); text.FontSize = 13; text.LineHeight = 22;
                if (row == 0) text.FontWeight = FontWeight.SemiBold;
                var cell = new Border { Child = text, Padding = new Thickness(12, 8), BorderBrush = GlassTheme.Line, BorderThickness = new Thickness(0, 0, 0, 1), Background = row == 0 ? Brush.Parse("#71395576") : row % 2 == 0 ? Brush.Parse("#260D1D31") : null };
                Grid.SetColumn(cell, column); Grid.SetRow(cell, row); grid.Children.Add(cell);
            }
        }
        return grid;
    }
}
