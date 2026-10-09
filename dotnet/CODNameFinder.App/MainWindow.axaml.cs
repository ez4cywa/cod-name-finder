using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text;
using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Markup.Xaml;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using Avalonia.VisualTree;
using CODNameFinder.Core;

namespace CODNameFinder.App;

/// <summary>Single-page UI; every configuration control uses direct typed access.</summary>
public partial class MainWindow : Window
{
    private readonly TextBox _folder = Edit("选择已导出的哈希资产文件夹");
    private readonly TextBox _snapshotFile = Edit("选择 JSON 增强快照或 IDS 原始快照");
    private readonly TextBox _cordycepDirectory = Edit("Cordycep 安装目录；捕获后可离线计算");
    private readonly TextBox _indexes = Edit("Saluki 目录或复制的 CDB 索引文件夹");
    private readonly TextBox _dictionary = Edit("可选：TXT / CSV / TSV / CDB / WNI 名称词典");
    private readonly TextBox _relatedFolder = Edit("可选：已导出的模型、材质、图像等文件夹");
    private readonly TextBox _output = Edit("独立的输出目录");
    private readonly TextBox _keyword = Edit("可选；在哈希命中后筛选名称，例如 mike4");
    private readonly TextBox _borrowedDictionary = Edit("可选：跨作品词典，仅提供候选，不进入校准");
    private readonly TextBox _communityCache = Edit("可选：社群 CSV 的本地缓存目录");
    private readonly ComboBox _game = DropDown();
    private readonly ComboBox _domain = DropDown();
    private readonly ComboBox _profile = DropDown();
    private readonly ComboBox _assetType = DropDown();
    private readonly ComboBox _backend = DropDown();
    private readonly ComboBox _inputMode = DropDown();
    private readonly ComboBox _cordycepScript = DropDown();
    private readonly Button _refreshScripts = ActionButton("刷新 BAT");
    private readonly Button _snapshotPicker = ActionButton("选择…");
    private readonly Button _attachCapture = ActionButton("读取已加载实例");
    private readonly Button _launchCapture = ActionButton("运行所选 BAT 并捕获");
    private readonly TextBlock _captureHint = Body("选择 BO7 或 COD2026；快照与字符串保存到输出目录的 captures 子目录。");
    private readonly Expander _captureOptions = new() { Header = "Cordycep 捕获 · BO7 / COD2026", IsExpanded = false, HorizontalAlignment = HorizontalAlignment.Stretch, Background = Brushes.Transparent, BorderBrush = GlassTheme.Line };
    private Grid? _folderRow;
    private Grid? _snapshotRow;
    private readonly CheckBox _exclude = new() { Content = "排除材质", IsChecked = true };
    private readonly CheckBox _low60 = new() { Content = "文件名仅保留低60位（仅生成待核验候选）" };
    private readonly CheckBox _crossAsset = new() { Content = "根据已知名称推测关联资产", IsChecked = true };
    private readonly CheckBox _community = new() { Content = "只读导入 cod-name-db 社群表（默认关闭）" };
    private readonly CheckBox _communityRefresh = new() { Content = "本次刷新社群缓存" };
    private readonly CheckBox _allowUnverified = new() { Content = "手动启用未证实域（需至少3对完整目标样本）" };
    private readonly CheckBox _anyway = new() { Content = "继续运行连续3次零产出的同方法（--anyway）" };
    private readonly TextBlock _domainHint = Body("按名称域选择算法；手动模式兼容旧任务。");
    private readonly Expander _advanced = new() { Header = "更多选项 · 借用词典、社区表与域验证", IsExpanded = false, HorizontalAlignment = HorizontalAlignment.Stretch, Background = Brushes.Transparent, BorderBrush = GlassTheme.Line };
    private readonly NumericUpDown _numberMax = new() { Minimum = 0, Maximum = 999, Value = 32, MinWidth = 110 };
    private readonly NumericUpDown _budget = new() { Minimum = 1000, Maximum = 1000000000, Increment = 10000, Value = 10000000, FormatString = "N0", MinWidth = 170 };
    private readonly NumericUpDown _minutes = new() { Minimum = 1, Maximum = 1440, Value = 120, MinWidth = 100 };
    private readonly Button _start = ActionButton("估算候选与耗时");
    private readonly Button _stop = ActionButton("停止并保存", false);
    private readonly Button _openResult = ActionButton("打开结果目录", false);
    private readonly Button _openCsv = ActionButton("打开新增 CSV", false);
    private readonly Button _relatedPicker = ActionButton("选择…");
    private readonly ProgressBar _progress = new() { Minimum = 0, Maximum = 10000000, Height = 5 };
    private readonly TextBlock _status = Body("就绪");
    private readonly TextBox _log = new() { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, FontFamily = new FontFamily("Microsoft YaHei UI, Segoe UI") };
    private readonly Grid _inputGrid = new() { ColumnDefinitions = new ColumnDefinitions("126,*"), Margin = new Thickness(0, 0, 12, 0) };
    private readonly ScrollViewer _inputScroll = new() { HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
    private readonly Queue<string> _messages = new();
    private CancellationTokenSource? _cancellation;
    private Task<RunReport>? _worker;
    private Task<EstimateReport>? _estimateWorker;
    private Task<CaptureReport>? _captureWorker;
    private CaptureReport? _captureResult;
    private EstimateReport? _estimate;
    private string? _estimateConfiguration;
    private bool _applyingConfiguration;
    private bool _refreshingScripts;
    private RunReport? _result;
    private TutorialWindow? _tutorial;
    private GlassWindowChrome? _chrome;
    private bool _closeAfterSave;
    private bool _stopTriggered;
    private long _progressEvents;
    public string ValidationStatusText => _status.Text ?? "";
    public bool EstimateAvailable => _estimate is not null && _estimate.Status is not ("stopped" or "cancelled");
    private bool IsBusy => _worker is not null || _estimateWorker is not null || _captureWorker is not null || _upstreamBusy;

    public MainWindow()
    {
        AvaloniaXamlLoader.Load(this);
        Icon = App.LoadApplicationIcon();
        GlassTheme.ConfigureWindow(this);
        foreach (var game in new[] { "BO4", "MW2019", "BOCW", "Vanguard", "MWII", "MWIII", "BO6", "BO7", "COD2026" }.Concat(GeneratedRegistry.Domains.Keys).Distinct()) AddChoice(_game, game, game);
        foreach (var profile in HashProfiles.All.Keys) AddChoice(_profile, profile, profile);
        AddChoice(_assetType, "自动识别全部非模型资产", "auto");
        foreach (var pair in AssetNames.Labels) AddChoice(_assetType, pair.Value + " · " + pair.Key, pair.Key);
        AddChoice(_backend, "自动选择 CPU / GPU", "auto");
        AddChoice(_backend, "CPU · Rust 内核", "cpu");
        AddChoice(_backend, "GPU · OpenCL", "gpu");
        AddChoice(_inputMode, "已导出的哈希文件夹", "folder");
        AddChoice(_inputMode, "离线资产快照 · JSON / IDS", "snapshot"); Select(_inputMode,"folder");
        Select(_game, "COD2026"); Select(_profile, "iw-resource63"); Select(_assetType, "xanim"); Select(_backend, "auto");
        RefreshDomains("asset");
        _output.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "CODNameFinder", "Results");
        if(Directory.Exists(@"D:\_tiqu\Cordycep"))_cordycepDirectory.Text=@"D:\_tiqu\Cordycep";
        _game.SelectionChanged += (_, _) => {RefreshDomains(_applyingConfiguration ? "" : DomainForAsset(Selected(_assetType))?.Id ?? "asset");RefreshCaptureScripts(resetSelection:true);};
        _cordycepDirectory.TextChanged += (_,_) => RefreshCaptureScripts(resetSelection:true);
        _cordycepScript.SelectionChanged += (_,_) => {if(!_refreshingScripts)UpdateCaptureControls();};
        _inputMode.SelectionChanged += (_, _) => UpdateInputControls();
        _domain.SelectionChanged += (_, _) => ApplyDomainSelection();
        _profile.SelectionChanged += (_, _) =>
        {
            if (!_applyingConfiguration && SelectedDomain is { Profile: { } expected } && Selected(_profile) != expected)
                Select(_domain, "");
        };
        _assetType.SelectionChanged += (_, _) =>
        {
            if (Selected(_assetType) == "material") _exclude.IsChecked = false;
            if (!_applyingConfiguration && SelectedDomain is { } current && !current.Kinds.Contains(Selected(_assetType)))
            {
                var matching = DomainForAsset(Selected(_assetType));
                if (matching is not null && matching.Id != Selected(_domain)) Select(_domain, matching.Id);
                else if (matching is null && Selected(_assetType) is "soundbankalias" or "bone" or "scriptfield" or "dvar" or "omnvar")
                { Select(_domain, ""); _profile.SelectedItem = null; _domainHint.Text = "该作品尚无此类型的默认名称域；需手动核对算法与完整目标样本。"; }
            }
            UpdateRelatedControls();
        };
        _crossAsset.IsCheckedChanged += (_, _) => UpdateRelatedControls();
        _community.IsCheckedChanged += (_, _) => UpdateAdvancedControls();
        ToolTip.SetTip(_crossAsset, "推测动画、声音、声音别名、图像和材质；新规则先回算来源并核对目标类型。所有推测名称仍需完整哈希命中及独立验证。");
        AutomationProperties.SetName(_relatedFolder, "其他已命名资产文件夹");
        AutomationProperties.SetName(_relatedPicker, "选择其他已命名资产文件夹");
        if (!Program.ValidationMode) LoadSettings();
        if (Program.ValidationMode && Program.ScreenshotPath is not null) _output.Text = "Results";
        RefreshCaptureScripts();
        UpdateRelatedControls();
        BuildContent();
        UpdateInputControls(); UpdateCaptureControls();
        WatchConfiguration();
        UpdateAdvancedControls();
        _start.Classes.Add("primary");
        _start.HorizontalAlignment = HorizontalAlignment.Stretch;
        if (Program.ValidationMode && Environment.GetCommandLineArgs().Contains("--minimum")) { Width = 880; Height = 740; }
        if (Program.ValidationMode && Environment.GetCommandLineArgs().Contains("--advanced")) _advanced.IsExpanded = true;
        if (Program.ValidationMode && Environment.GetCommandLineArgs().Contains("--capture")) _captureOptions.IsExpanded = true;
        if (Program.ValidationMode && Environment.GetCommandLineArgs().Contains("--snapshot")) Select(_inputMode,"snapshot");
        _start.Click += async (_, _) => await HandleStartAsync();
        _stop.Click += (_, _) => StopAndSave();
        _openResult.Click += (_, _) => OpenPath(ResultDirectory);
        _openCsv.Click += (_, _) => OpenPath(_result?.NewNamesCsv);
        _relatedPicker.Click += async (_, _) => await PickDirectory(_relatedFolder);
        _snapshotPicker.Click += async (_, _) => await PickSnapshot();
        _attachCapture.Click += async (_, _) => await CaptureConfigurationAsync(false);
        _launchCapture.Click += async (_, _) => await CaptureConfigurationAsync(true);
        _refreshScripts.Click += (_,_) => RefreshCaptureScripts();
        KeyDown += (_, args) =>
        {
            if (args.Key == Key.F1) { OpenTutorial(); args.Handled = true; }
        };
        Closing += (_, args) =>
        {
            if (IsBusy)
            {
                args.Cancel = true;
                _closeAfterSave = true;
                StopAndSave();
            }
            else if (!Program.ValidationMode) SaveSettings(Configuration());
        };
    }

    private void BuildContent()
    {
        var root = new Grid { Margin = new Thickness(22, 12, 22, 18), RowDefinitions = new RowDefinitions("Auto,*,Auto,Auto,Auto"), RowSpacing = 10 };
        _chrome = new GlassWindowChrome(this, OpenTutorial);
        AddRoot(root, _chrome.Surface, 0);
        FormRow("输入来源", _inputMode);
        _folderRow=PathPicker(_folder); FormRow("哈希文件夹", _folderRow);
        _snapshotRow=Pair(_snapshotFile,_snapshotPicker); FormRow("离线快照", _snapshotRow);
        var algorithms = new Grid { ColumnDefinitions = new ColumnDefinitions("126,*,190"), ColumnSpacing = 8 };
        algorithms.Children.Add(_game); Grid.SetColumn(_domain, 1); algorithms.Children.Add(_domain); Grid.SetColumn(_profile, 2); algorithms.Children.Add(_profile);
        AutomationProperties.SetName(_game, "作品"); AutomationProperties.SetName(_domain, "名称域"); AutomationProperties.SetName(_profile, "哈希规则");
        FormRow("作品、域与算法", algorithms);
        _domainHint.FontSize = 12; _domainHint.Classes.Add("secondary");
        FormRow("域验证状态", _domainHint);
        FormRow("资产类型", Pair(_assetType, _exclude));
        FormRow("已有名称索引", PathPicker(_indexes));
        FormRow("补充名称词典", PathPicker(_dictionary, file: true));
        FormRow("关联名称推测", _crossAsset);
        FormRow("其他已命名资产", Pair(_relatedFolder, _relatedPicker));
        FormRow("输出目录", PathPicker(_output));
        var captureForm=new StackPanel {Spacing=8,Margin=new Thickness(0,8,0,4)};
        captureForm.Children.Add(PathPicker(_cordycepDirectory));
        var scriptLabel=Body("启动脚本 · 目录根 BAT");scriptLabel.FontSize=12;scriptLabel.Classes.Add("secondary");
        captureForm.Children.Add(scriptLabel);captureForm.Children.Add(Pair(_cordycepScript,_refreshScripts));
        captureForm.Children.Add(Pair(_attachCapture,_launchCapture));
        _captureHint.FontSize=12;_captureHint.Classes.Add("secondary");captureForm.Children.Add(_captureHint);
        _captureOptions.Content=captureForm;FormRow("捕获私有快照",_captureOptions);
        FormRow("结果关键词", _keyword);
        FormRow("运算方式", Pair(_backend, _low60));
        var limits = new Grid { ColumnDefinitions = new ColumnDefinitions("180,Auto,115,Auto,*"), ColumnSpacing = 8 };
        limits.Children.Add(_budget); var times = Body("次候选计算，最多"); times.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(times, 1); limits.Children.Add(times); Grid.SetColumn(_minutes, 2); limits.Children.Add(_minutes);
        var minutes = Body("分钟"); minutes.VerticalAlignment = VerticalAlignment.Center; Grid.SetColumn(minutes, 3); limits.Children.Add(minutes);
        FormRow("本次预算", limits);
        var extra = new Grid { ColumnDefinitions = new ColumnDefinitions("126,*"), RowSpacing = 8, Margin = new Thickness(0, 8, 0, 4) };
        void AdvancedRow(string label, Control control)
        {
            var row = extra.RowDefinitions.Count; extra.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            var caption = Body(label); caption.Foreground = GlassTheme.Secondary; caption.VerticalAlignment = VerticalAlignment.Center;
            caption.Margin = new Thickness(0, 0, 10, 0); Grid.SetRow(caption, row); extra.Children.Add(caption);
            Grid.SetRow(control, row); Grid.SetColumn(control, 1); extra.Children.Add(control);
            AutomationProperties.SetName(control, label);
        }
        AdvancedRow("跨作品候选", PathPicker(_borrowedDictionary, file: true));
        AdvancedRow("社群名称表", _community);
        AdvancedRow("同步选项", _communityRefresh);
        AdvancedRow("社群缓存", PathPicker(_communityCache));
        AdvancedRow("未证实域", _allowUnverified);
        AdvancedRow("方法守卫", _anyway);
        AdvancedRow("末尾数字上限", _numberMax);
        _advanced.Content = extra; FormRow("更多选项", _advanced);
        BuildUpstreamControls();
        var form = new Grid { RowDefinitions = new RowDefinitions("Auto,*"), RowSpacing = 10 };
        var formHeading = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        var inputHeading = Body("输入与输出"); inputHeading.Classes.Add("section-title"); formHeading.Children.Add(inputHeading);
        var instruction = Body("选择输入来源与对应作品的哈希规则"); instruction.FontSize = 12; instruction.Classes.Add("secondary");
        Grid.SetColumn(instruction, 1); formHeading.Children.Add(instruction); form.Children.Add(formHeading);
        _inputScroll.Content = _inputGrid; Grid.SetRow(_inputScroll, 1); form.Children.Add(_inputScroll);
        AddRoot(root, GlassTheme.Panel(form, new Thickness(18, 14)), 1);
        var actions = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto,Auto"), ColumnSpacing = 10 };
        foreach (var action in new[] { _start, _stop, _openResult, _openCsv })
        {
            action.Classes.Add("action"); AutomationProperties.SetName(action, (string?)action.Content ?? "");
        }
        actions.Children.Add(_start); Grid.SetColumn(_stop, 1); actions.Children.Add(_stop); Grid.SetColumn(_openResult, 2); actions.Children.Add(_openResult); Grid.SetColumn(_openCsv, 3); actions.Children.Add(_openCsv);
        AddRoot(root, actions, 2);
        var progress = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto"), RowSpacing = 8 };
        var progressHeading = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 16 };
        var progressLabel = Body("查找进度"); progressLabel.Classes.Add("secondary"); progressLabel.FontSize = 12; progressLabel.VerticalAlignment = VerticalAlignment.Center;
        progressHeading.Children.Add(progressLabel); Grid.SetColumn(_status, 1); progressHeading.Children.Add(_status);
        AutomationProperties.SetName(_status, "本次名称计算的状态");
        AutomationProperties.SetName(_progress, "候选名称计算进度");
        AutomationProperties.SetName(_log, "运行日志"); _log.Classes.Add("log");
        progress.Children.Add(progressHeading); AddRoot(progress, _progress, 1); AddRoot(progress, _log, 2);
        AddRoot(root, GlassTheme.Panel(progress, new Thickness(16, 12), 18), 3);
        var note = Body("完整哈希命中并回算通过后才输出；排除 Saluki 已有名称。候选覆盖有限，不保证所有文件都能命名。");
        note.FontSize = 12; note.Classes.Add("secondary"); note.Margin = new Thickness(4, 0);
        AddRoot(root, note, 4); Content = GlassTheme.Backdrop(root);
    }

    private static TextBox Edit(string hint)
    {
        var edit = new TextBox { PlaceholderText = hint, PlaceholderForeground = GlassTheme.Secondary, VerticalAlignment = VerticalAlignment.Center };
        // The Fluent template assigns a DynamicResource directly to its placeholder Opacity.
        // A nearest-control resource overrides that value without replacing the native template.
        edit.Resources["TextControlPlaceholderOpacity"] = 1d;
        return edit;
    }
    private static ComboBox DropDown() => new() { HorizontalAlignment = HorizontalAlignment.Stretch, VerticalAlignment = VerticalAlignment.Center };
    private static Button ActionButton(string text, bool enabled = true) => new() { Content = text, IsEnabled = enabled, HorizontalContentAlignment = HorizontalAlignment.Center };
    private static TextBlock Body(string text) => new() { Text = text, TextWrapping = TextWrapping.Wrap };
    private static void AddRoot(Grid root, Control control, int row) { Grid.SetRow(control, row); root.Children.Add(control); }
    private static void AddChoice(ComboBox box, string text, string id) => box.Items.Add(new ComboBoxItem { Content = text, Tag = id });
    private static string Selected(ComboBox box) => (box.SelectedItem as ComboBoxItem)?.Tag as string ?? "";
    private static void Select(ComboBox box, string id)
    {
        foreach (var item in box.Items.OfType<ComboBoxItem>()) if ((string?)item.Tag == id) { box.SelectedItem = item; return; }
    }
    private static Grid Pair(Control left, Control right)
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 10 };
        row.Children.Add(left); right.VerticalAlignment = VerticalAlignment.Center; Grid.SetColumn(right, 1); row.Children.Add(right); return row;
    }
    private void FormRow(string label, Control control)
    {
        var row = _inputGrid.RowDefinitions.Count; _inputGrid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        var text = new TextBlock { Text = label, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 10, 0), Foreground = GlassTheme.Secondary };
        AutomationProperties.SetName(control, label);
        Grid.SetRow(text, row); _inputGrid.Children.Add(text); Grid.SetRow(control, row); Grid.SetColumn(control, 1); _inputGrid.Children.Add(control);
        _inputGrid.RowSpacing = 6;
    }
    private Grid PathPicker(TextBox edit, bool file = false)
    {
        var choose = ActionButton("选择…");
        AutomationProperties.SetName(choose, file ? "选择补充名称词典" : "选择 " + (edit.PlaceholderText ?? "文件夹"));
        choose.Click += async (_, _) => { if (file) await PickDictionary(edit); else await PickDirectory(edit); };
        return Pair(edit, choose);
    }
    private async Task PickDirectory(TextBox edit)
    {
        try
        {
            var selected = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions { Title = "选择文件夹", AllowMultiple = false });
            if (selected.Count > 0 && selected[0].TryGetLocalPath() is { } path) edit.Text = path;
        }
        catch (Exception exception) { _status.Text = "无法选择文件夹：" + exception.Message; }
    }
    private async Task PickDictionary(TextBox edit)
    {
        try
        {
            var selected = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = "选择名称词典", AllowMultiple = false,
                FileTypeFilter = [new FilePickerFileType("名称词典") { Patterns = ["*.txt", "*.tsv", "*.csv", "*.cdb", "*.wni"] }]
            });
            if (selected.Count > 0 && selected[0].TryGetLocalPath() is { } path) edit.Text = path;
        }
        catch (Exception exception) { _status.Text = "无法选择名称词典：" + exception.Message; }
    }
    private async Task PickSnapshot()
    {
        try
        {
            var selected=await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title="选择离线资产快照",AllowMultiple=false,
                FileTypeFilter=[new FilePickerFileType("资产快照") {Patterns=["*.json","*.ids"]}]
            });
            if(selected.Count>0&&selected[0].TryGetLocalPath() is { } path)_snapshotFile.Text=path;
        }
        catch(Exception exception){_status.Text="无法选择快照："+exception.Message;}
    }
    private void UpdateInputControls()
    {
        var snapshot=Selected(_inputMode)=="snapshot";
        if(_folderRow is not null)_folderRow.IsEnabled=!snapshot;
        if(_snapshotRow is not null)_snapshotRow.IsEnabled=snapshot;
        ToolTip.SetTip(_snapshotFile,"JSON 保留原始键与关联字符串；现代 IDS 必须带同名 .pools.txt，按其中资产类型识别。63 位别名只作线索，不能认证满 64 位输出。");
        AutomationProperties.SetName(_inputMode,"输入来源：文件夹或离线资产快照");
        AutomationProperties.SetName(_snapshotPicker,"选择 JSON 或 IDS 离线快照");
    }
    private void UpdateCaptureControls()
    {
        var supported=Selected(_game) is "BO7" or "COD2026";
        _attachCapture.IsEnabled=supported&&!IsBusy;
        _launchCapture.IsEnabled=supported&&!IsBusy&&Selected(_cordycepScript).Length>0;
        _cordycepDirectory.IsEnabled=_cordycepScript.IsEnabled=_refreshScripts.IsEnabled=supported&&!IsBusy;
        _captureHint.Text=supported
            ?$"当前作品：{Selected(_game)}。读取已加载实例保存当前集合；运行所选 BAT 按脚本加载。快照仅代表已加载集合；停止后需重新捕获完整快照。"+(Selected(_cordycepScript).Length==0?" 当前目录没有可选 BAT，请选择 Cordycep 目录并刷新。":"")
            :"Cordycep 捕获当前仅支持 BO7 / COD2026；其他作品可使用已有文件夹或离线快照。";
        AutomationProperties.SetName(_attachCapture,"读取已加载 Cordycep 实例并保存完整快照");
        AutomationProperties.SetName(_launchCapture,"运行所选 BAT 启动 Cordycep 并捕获已加载集合");
        AutomationProperties.SetName(_cordycepScript,"选择 Cordycep 目录里的 BAT 启动脚本");
        AutomationProperties.SetName(_refreshScripts,"重新读取 Cordycep 目录里的 BAT 文件");
        ToolTip.SetTip(_cordycepScript,"只列出所选目录根的 BAT。更改目录或作品时重新选择默认脚本；刷新时保留当前选择。");
    }
    private void RefreshCaptureScripts(bool resetSelection=false,string? explicitSelection=null)
    {
        if(IsBusy)return;
        var previous=explicitSelection??(resetSelection?null:Selected(_cordycepScript));
        _refreshingScripts=true;
        try
        {
            var scripts=CordycepScripts.Enumerate(_cordycepDirectory.Text?.Trim()??"");
            _cordycepScript.Items.Clear();foreach(var script in scripts)AddChoice(_cordycepScript,script,script);
            _cordycepScript.SelectedItem=null;
            Select(_cordycepScript,CordycepScripts.Select(scripts,Selected(_game),previous));
        }
        catch(Exception exception)when(exception is IOException or UnauthorizedAccessException or ArgumentException)
        {_cordycepScript.Items.Clear();_cordycepScript.SelectedItem=null;AppendLog("无法读取 BAT 启动脚本："+exception.Message);}
        finally{_refreshingScripts=false;UpdateCaptureControls();}
    }
    private void UpdateRelatedControls()
    {
        var supported = Selected(_assetType) is "auto" or "xanim" or "sndasset" or "soundbank" or "soundbanktransient" or "soundbankalias" or "image" or "material";
        _crossAsset.IsEnabled = supported;
        _relatedFolder.IsEnabled = _relatedPicker.IsEnabled = supported && _crossAsset.IsChecked == true;
        ToolTip.SetTip(_relatedFolder, supported ? "可选名称线索目录；勾选关联名称推测后启用。" : "仅动画、声音、声音库或自动识别目标使用关联推测；保留已选路径。");
    }

    private RegistryDomain? SelectedDomain => GeneratedRegistry.Domains.TryGetValue(Selected(_game), out var domains)
        ? domains.FirstOrDefault(domain => domain.Id == Selected(_domain)) : null;

    private RegistryDomain? DomainForAsset(string kind)
    {
        if (!GeneratedRegistry.Domains.TryGetValue(Selected(_game), out var domains)) return null;
        if (kind is "soundbankalias" or "bone" or "scriptfield" or "dvar" or "omnvar")
            return domains.FirstOrDefault(domain => domain.Kinds.Contains(kind));
        return domains.FirstOrDefault(domain => domain.Id == "asset");
    }

    private void RefreshDomains(string preferred)
    {
        _domain.Items.Clear(); AddChoice(_domain, "手动算法 · 兼容旧任务", "");
        if (GeneratedRegistry.Domains.TryGetValue(Selected(_game), out var domains))
            foreach (var domain in domains)
                AddChoice(_domain, domain.Label + (domain.Status == "evidence" ? " · 已实证" : domain.Status == "unknown" ? " · 未证实" : " · 候选"), domain.Id);
        Select(_domain, preferred); if (_domain.SelectedItem is null) _domain.SelectedIndex = 0;
        ApplyDomainSelection();
    }

    private void ApplyDomainSelection()
    {
        var domain = SelectedDomain;
        if (domain is null)
        {
            _domainHint.Text = "手动模式：直接选择算法，兼容旧配置；请按作品及名称类型核对规则。";
            _profile.PlaceholderText = "手动选择哈希规则";
            return;
        }
        if (!_applyingConfiguration)
        {
            if (domain.Profile is { } profile) Select(_profile, profile);
            else _profile.SelectedItem = null;
            if (Selected(_assetType) != "auto" && !domain.Kinds.Contains(Selected(_assetType)))
            {
                var kind = domain.Kinds.FirstOrDefault(AssetNames.Labels.ContainsKey);
                if (kind is not null) Select(_assetType, kind);
            }
        }
        _profile.PlaceholderText = domain.Profile is null ? "必须手动选择算法" : "哈希规则";
        _domainHint.Text = domain.Status == "unknown"
            ? "未证实域：无默认算法。需手动算法、更多选项允许开关，及补充词典中至少3对同域完整目标哈希/名称；低60位不可解除门控。"
            : domain.Status == "candidate"
                ? "候选域：仅对真实目标哈希验证。声音路径可保留反斜杠，请按该域规则选择。"
                : $"已实证：{domain.Profile} · 按当前名称域验证；所选资产类型仍需与目标文件一致。";
        ToolTip.SetTip(_domain, domain.Source);
    }

    private void UpdateAdvancedControls()
    {
        _communityRefresh.IsEnabled = _community.IsChecked == true;
        _communityCache.IsEnabled = _community.IsChecked == true;
        ToolTip.SetTip(_borrowedDictionary, "借用名称只生成候选；不计入当前作品校准或命名惯例。仍需命中完整目标哈希。" );
        ToolTip.SetTip(_community, "可选联网下载到本地缓存；逐行回算通过才作为已验证名称，其余仅候选词汇。不会提交或公开发布名称。" );
        ToolTip.SetTip(_anyway, "只覆盖连续零产出方法的启动守卫；已扫区间仍可复用，域门控和独立回算仍生效。" );
    }

    private void WatchConfiguration()
    {
        foreach (var edit in new[] { _folder, _snapshotFile, _cordycepDirectory, _indexes, _dictionary, _relatedFolder, _output, _keyword, _borrowedDictionary, _communityCache })
            edit.TextChanged += (_, _) => InvalidateEstimate();
        foreach (var box in new[] { _inputMode, _game, _domain, _profile, _assetType, _backend })
            box.SelectionChanged += (_, _) => InvalidateEstimate();
        foreach (var check in new[] { _exclude, _low60, _crossAsset, _community, _communityRefresh, _allowUnverified, _anyway })
            check.IsCheckedChanged += (_, _) => InvalidateEstimate();
        foreach (var number in new[] { _budget, _minutes, _numberMax })
            number.ValueChanged += (_, _) => InvalidateEstimate();
    }

    private void InvalidateEstimate()
    {
        if (_applyingConfiguration || IsBusy) return;
        if (_estimate is not null) _status.Text = "配置已修改，请重新估算候选与耗时。";
        _estimate = null; _estimateConfiguration = null; StartCaption("估算候选与耗时");
    }

    private static Config Clone(Config config) => JsonSerializer.Deserialize(
        JsonSerializer.Serialize(config, FinderJsonContext.Default.Config), FinderJsonContext.Default.Config)!;
    private static string ConfigurationKey(Config config) => JsonSerializer.Serialize(config, FinderJsonContext.Default.Config);

    public Config Configuration() => new()
    {
        InputMode=Selected(_inputMode),SnapshotFile=_snapshotFile.Text?.Trim()??"",
        Folder = _folder.Text?.Trim() ?? "", Indexes = _indexes.Text?.Trim() ?? "", Output = _output.Text?.Trim() ?? "",
        Dictionary = _dictionary.Text?.Trim() ?? "", RelatedFolder = _relatedFolder.Text?.Trim() ?? "", Keyword = _keyword.Text?.Trim() ?? "",
        Game = Selected(_game), Profile = Selected(_profile), AssetType = Selected(_assetType), Backend = Selected(_backend),
        ExcludeMaterial = _exclude.IsChecked == true, Low60 = _low60.IsChecked == true, CrossAsset = _crossAsset.IsChecked == true,
        Budget = (long)(_budget.Value ?? 10000000), Seconds = (int)(_minutes.Value ?? 120) * 60, NumberMax = (int)(_numberMax.Value ?? 32),
        HashDomain = Selected(_domain), AllowUnverifiedDomain = _allowUnverified.IsChecked == true,
        BorrowedDictionary = _borrowedDictionary.Text?.Trim() ?? "", Community = _community.IsChecked == true,
        CommunityCache = _communityCache.Text?.Trim() ?? "", CommunityRefresh = _communityRefresh.IsChecked == true,
        Anyway = _anyway.IsChecked == true
    };

    public void ApplyConfiguration(Config config)
    {
        _applyingConfiguration = true;
        try
        {
            _folder.Text = config.Folder; _indexes.Text = config.Indexes; _output.Text = config.Output; _dictionary.Text = config.Dictionary;
            Select(_inputMode,config.InputMode);_snapshotFile.Text=config.SnapshotFile;
            _keyword.Text = config.Keyword; _relatedFolder.Text = config.RelatedFolder;
            Select(_game, config.Game); Select(_domain, config.HashDomain); Select(_profile, config.Profile); Select(_assetType, config.AssetType); Select(_backend, config.Backend);
            _exclude.IsChecked = config.ExcludeMaterial; _low60.IsChecked = config.Low60; _crossAsset.IsChecked = config.CrossAsset;
            _budget.Value = Math.Clamp(config.Budget, 1000, 1000000000); _minutes.Value = Math.Clamp(config.Seconds / 60, 1, 1440);
            _numberMax.Value = config.NumberMax; _borrowedDictionary.Text = config.BorrowedDictionary;
            _community.IsChecked = config.Community; _communityRefresh.IsChecked = config.CommunityRefresh;
            _communityCache.Text = config.CommunityCache; _allowUnverified.IsChecked = config.AllowUnverifiedDomain; _anyway.IsChecked = config.Anyway;
            ApplyDomainSelection(); UpdateRelatedControls(); UpdateAdvancedControls();UpdateInputControls();UpdateCaptureControls();
        }
        finally { _applyingConfiguration = false; }
        InvalidateEstimate();
    }

    private async Task HandleStartAsync()
    {
        if (IsBusy) return;
        var config = Configuration();
        if (EstimateAvailable && _estimateConfiguration == ConfigurationKey(config))
            await ExecuteRunAsync(Clone(config));
        else await EstimateConfigurationAsync(config);
    }

    private bool ValidateConfiguration(Config config)
    {
        try
        {
            config.Validate();
            var domain = GeneratedRegistry.Domains.TryGetValue(config.Game, out var domains)
                ? domains.FirstOrDefault(item => item.Id == config.HashDomain) : null;
            if (config.HashDomain.Length > 0 && domain is null) throw new ArgumentException("所选作品没有该名称域，请重新选择。");
            if (domain?.Profile is { } expected && config.Profile != expected)
                throw new ArgumentException($"此名称域使用 {expected}；如需其他算法，请选择手动域。");
            if (domain?.Status == "unknown")
            {
                if (!config.AllowUnverifiedDomain) throw new ArgumentException("未证实域需要在更多选项中手动启用，并提供至少3对同域完整目标样本。");
                if (config.Low60) throw new ArgumentException("仅低60位目标不能解除未证实域门控。");
                if (string.IsNullOrWhiteSpace(config.Dictionary)) throw new ArgumentException("请用补充名称词典提供至少3对同域完整目标哈希/名称；借用词典不能作为校准证据。");
            }
            return true;
        }
        catch (Exception exception) { _status.Text = "无法开始：" + exception.Message; AppendLog(_status.Text); return false; }
    }

    private void BeginOperation(Config config, bool estimating)
    {
        _inputGrid.IsEnabled = false; _start.IsEnabled = false; _stop.IsEnabled = true; _openResult.IsEnabled = _openCsv.IsEnabled = false;
        _progress.Maximum = config.Budget; _progress.Value = 0; _progress.IsIndeterminate = estimating;
        _result = null;_captureResult=null; _stopTriggered = false; _cancellation = new CancellationTokenSource();ResetUpstreamResult(config.Low60);
    }

    private void FinishOperation()
    {
        _cancellation?.Dispose(); _cancellation = null; _inputGrid.IsEnabled = true; UpdateRelatedControls(); UpdateAdvancedControls();UpdateInputControls();UpdateCaptureControls();
        _progress.IsIndeterminate = false; _start.IsEnabled = true; _stop.IsEnabled = false;
        UpdateUpstreamControls();
        if (_closeAfterSave) Close();
    }

    private void StartCaption(string text)
    {
        _start.Content = text; AutomationProperties.SetName(_start, text);
    }

    public async Task<CaptureReport?> CaptureConfigurationAsync(bool launch=false)
    {
        if(IsBusy)return null;
        var config=Configuration();var directory=_cordycepDirectory.Text?.Trim()??"";
        if(!Directory.Exists(directory))
        {_status.Text="请选择存在的 Cordycep 安装目录。";AppendLog(_status.Text);return null;}
        if(config.Game is not ("BO7" or "COD2026"))
        {_status.Text="请先选择 BO7 或 COD2026，再捕获对应实例。";AppendLog(_status.Text);return null;}
        if(string.IsNullOrWhiteSpace(config.Output))
        {_status.Text="请先选择快照输出目录。";AppendLog(_status.Text);return null;}
        var script=Selected(_cordycepScript);
        if(launch)
        {
            try{CordycepScripts.Validate(directory,script);}
            catch(ArgumentException exception){_status.Text=exception.Message;AppendLog(_status.Text);return null;}
        }
        _estimate=null;_estimateConfiguration=null;_messages.Clear();_log.Text="";_progressEvents=0;
        BeginOperation(config,estimating:true);StartCaption("正在捕获…");
        var cancellation=_cancellation!.Token;
        _status.Text=launch?$"运行 {script} 并捕获 Cordycep 已加载集合…":"读取已加载的 Cordycep 实例…";AppendLog(_status.Text);
        try
        {
            var output=Path.Combine(Path.GetFullPath(config.Output),"captures");
            _captureWorker=Task.Run(()=>Pipeline.Capture(directory,config.Game,output,launch,(processed,message)=>Dispatcher.UIThread.Post(()=>
            {
                _progressEvents++;_status.Text=message;AppendLog(message);
                if(Program.StopAfterCandidates>0&&processed>=Program.StopAfterCandidates&&!_stopTriggered)
                {_stopTriggered=true;StopAndSave();}
            }),cancellation,script:launch?script:null));
            var captured=await _captureWorker;_captureResult=captured;
            _openResult.IsEnabled=!string.IsNullOrEmpty(captured.SnapshotFile);
            if(captured.Complete&&captured.Status=="completed"&&!cancellation.IsCancellationRequested)
            {
                _applyingConfiguration=true;
                try {Select(_inputMode,"snapshot");_snapshotFile.Text=captured.SnapshotFile;}
                finally {_applyingConfiguration=false;}
                UpdateInputControls();
                _status.Text=$"捕获完成 · {captured.Records:N0} 个资产 · {captured.Strings:N0} 条字符串。快照已选中，请查看估算后确认计算。";
                AppendLog(_status.Text);AppendLog("快照："+captured.SnapshotFile);AppendLog("关联字符串随快照自动导入。");
            }
            else
            {
                _status.Text=$"捕获未完成 · 已保存 {captured.Records:N0} 个资产、{captured.Strings:N0} 条字符串的排查报告；请重新捕获完整快照。";
                AppendLog(_status.Text);if(!string.IsNullOrEmpty(captured.Message))AppendLog(captured.Message);
                if(!string.IsNullOrEmpty(captured.SnapshotFile))AppendLog("不完整捕获报告："+captured.SnapshotFile);
            }
            if(!Program.ValidationMode)SaveSettings(Configuration());
            return captured;
        }
        catch(OperationCanceledException)
        {_status.Text="捕获已停止，请查看输出目录中的捕获报告。";AppendLog(_status.Text);return null;}
        catch(Exception exception)
        {_status.Text="捕获失败："+exception.Message;AppendLog(_status.Text);return null;}
        finally {_captureWorker=null;StartCaption("估算候选与耗时");FinishOperation();}
    }

    public void ApplyCaptureValidation(string directory,string game,string output,string? script=null)
    {
        _cordycepDirectory.Text=directory;_output.Text=output;Select(_game,game);_captureOptions.IsExpanded=true;
        RefreshCaptureScripts(explicitSelection:script);
        if(script is {Length:>0}&&!Selected(_cordycepScript).Equals(script,StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("验证所选 BAT 不在 Cordycep 目录里："+script);
    }

    public async Task<EstimateReport?> EstimateConfigurationAsync(Config? supplied = null)
    {
        if (IsBusy) return null;
        var config = Clone(supplied ?? Configuration());
        if (supplied is not null) ApplyConfiguration(config);
        if (!ValidateConfiguration(config)) return null;
        _estimate = null; _estimateConfiguration = null;
        _messages.Clear(); _log.Text = ""; _progressEvents = 0;
        BeginOperation(config, estimating: true); StartCaption("正在估算…");
        _status.Text = config.Community ? "同步可选社区词典…" : "估算候选、耗时与 Saluki 差集…";
        AppendLog(_status.Text); var cancellation = _cancellation!.Token;
        try
        {
            _estimateWorker = Task.Run(() =>
            {
                if (config.Community)
                {
                    var synced = Pipeline.SyncCommunity(config, cancellation);
                    config.CommunityRefresh = false;
                    Dispatcher.UIThread.Post(() => AppendLog("社区缓存已同步，将使用本地快照进行只读估算。"));
                    if (!string.IsNullOrWhiteSpace(synced)) Dispatcher.UIThread.Post(() => AppendLog(synced.Length > 1600 ? synced[..1600] : synced));
                }
                return Pipeline.Estimate(config, (_, message) => Dispatcher.UIThread.Post(() =>
                {
                    _progressEvents++; _status.Text = message; AppendLog(message);
                }), cancellation);
            }, cancellation);
            var estimate = await _estimateWorker;
            if (cancellation.IsCancellationRequested || estimate.Status != "estimated")
            { _status.Text = "估算已停止，未开始名称计算。"; AppendLog(_status.Text); StartCaption("估算候选与耗时"); return null; }
            if (config.Community)
            {
                _applyingConfiguration = true;
                try { _communityRefresh.IsChecked = false; }
                finally { _applyingConfiguration = false; }
            }
            _estimate = estimate; _estimateConfiguration = ConfigurationKey(config);
            if (!Program.ValidationMode) SaveSettings(config);
            ShowEstimate(estimate); StartCaption("确认计算并导出");
            return estimate;
        }
        catch (OperationCanceledException)
        { _status.Text = "估算已停止，未开始名称计算。"; AppendLog(_status.Text); StartCaption("估算候选与耗时"); return null; }
        catch (Exception exception)
        { _status.Text = "估算失败：" + exception.Message; AppendLog(_status.Text); StartCaption("估算候选与耗时"); return null; }
        finally { _estimateWorker = null; FinishOperation(); }
    }

    private static string Duration(double seconds) => seconds >= 3600 ? $"{seconds / 3600:0.##}小时" : seconds >= 60 ? $"{seconds / 60:0.##}分钟" : $"{seconds:0.##}秒";
    private void ShowEstimate(EstimateReport estimate)
    {
        var range = estimate.SecondsRange.Length >= 2 ? Duration(estimate.SecondsRange[0]) + "～" + Duration(estimate.SecondsRange[1]) : "尚无法估计";
        _status.Text = $"估算完成 · 未知目标 {estimate.TargetCount:N0} · 本次最多 {estimate.BudgetedCandidates:N0} 次 · 预计 {range}；确认后开始计算。";
        AppendLog(_status.Text);
        AppendLog($"全部候选空间 {estimate.CandidateTotal:N0} · 已扫候选可复用至少 {estimate.CachedCandidates:N0} · 随机碰撞期望 {estimate.CollisionExpectation:0.###E+0}。");
        AppendLog("耗时按本机 CPU 基准给出区间；GPU、实际命中、目标缩小与索引导出会影响最终时间。命中仍需完整键独立回算。");
        if (estimate.Coverage.ValueKind == JsonValueKind.Object && estimate.Coverage.TryGetProperty("types", out var kinds) && kinds.ValueKind == JsonValueKind.Array)
            foreach (var kind in kinds.EnumerateArray())
            {
                var id = kind.GetProperty("kind").GetString() ?? "";
                var label = AssetNames.Labels.TryGetValue(id, out var friendly) ? friendly : id;
                AppendLog($"Saluki 差集 · {label}：目标 {kind.GetProperty("targets").GetInt64():N0}，已有键 {kind.GetProperty("saluki_known").GetInt64():N0}，未知 {kind.GetProperty("unknown").GetInt64():N0}。");
            }
    }

    public async Task<RunReport?> RunConfigurationAsync(Config? supplied = null)
    {
        if (IsBusy) return null;
        var config = Clone(supplied ?? Configuration());
        if (!EstimateAvailable || _estimateConfiguration != ConfigurationKey(config))
            if (await EstimateConfigurationAsync(config) is null) return null;
        // Validation commands execute automatically after one real estimate.
        // The ordinary button only reaches execution on its second click.
        var quoted = JsonSerializer.Deserialize(_estimateConfiguration!, FinderJsonContext.Default.Config)!;
        return await ExecuteRunAsync(quoted);
    }

    private async Task<RunReport?> ExecuteRunAsync(Config config)
    {
        if (IsBusy || !ValidateConfiguration(config)) return null;
        if (!Program.ValidationMode) SaveSettings(config);
        BeginOperation(config, estimating: false); _progressEvents = 0; _status.Text = "开始查找…"; AppendLog(_status.Text);
        var cancellation = _cancellation!.Token;
        try
        {
            _worker = Task.Run(() => Pipeline.Run(config, (processed, message) => Dispatcher.UIThread.Post(() =>
            {
                _progressEvents++; _progress.Value = Math.Clamp((double)processed, 0, _progress.Maximum); _status.Text = message; AppendLog(message);
                if (Program.StopAfterCandidates > 0 && processed >= Program.StopAfterCandidates && !_stopTriggered)
                { _stopTriggered = true; StopAndSave(); }
            }), cancellation));
            _result = await _worker;
            _status.Text = $"{(_result.Status == "completed" ? "完成" : "本次停止或预算耗尽")} · 验证 {_result.VerifiedTargetMatches:N0} 项 · 排除已有 {_result.ExcludedExisting:N0} 项 · 输出 {_result.Entries:N0} 项";
            _openResult.IsEnabled = true; _openCsv.IsEnabled = !string.IsNullOrEmpty(_result.NewNamesCsv);
            if (_result.Status == "completed") _progress.Value = _progress.Maximum;
            AppendLog(_status.Text); AppendLog("结果目录：" + ResultDirectory);
            return _result;
        }
        catch (Exception exception)
        {
            _status.Text = "运行失败：" + exception.Message + "\n已保存的工作文件仍保留在输出目录。"; AppendLog(_status.Text); return null;
        }
        finally
        {
            _worker = null; _estimateConfiguration = null; StartCaption("估算候选与耗时"); FinishOperation();
            if(!_closeAfterSave&&UpstreamSubmission.ShouldAutoSubmit(_result,config.Low60,_upstreamAuto.IsChecked==true))
                await PerformUpstreamAsync("prepare",automatic:true);
        }
    }

    public void StopAndSave()
    {
        if (!IsBusy) return;
        if(_upstreamBusy)
        {_upstreamCancellation?.Cancel();_stop.IsEnabled=false;_upstreamHint.Text="停止贡献操作，等待后台退出；计算结果已保留。";return;}
        _stopTriggered=true;_cancellation?.Cancel(); _stop.IsEnabled = false;
        _status.Text = _captureWorker is not null ? "停止捕获，等待保存不完整报告并安全退出…" : _estimateWorker is not null ? "停止估算，等待后台退出…" : "等待当前批次保存并导出已验证结果…";
    }
    private void AppendLog(string? message)
    {
        if (string.IsNullOrEmpty(message)) return; _messages.Enqueue(message);
        while (_messages.Count > 300) _messages.Dequeue();
        _log.Text = string.Join(Environment.NewLine, _messages); _log.CaretIndex = _log.Text.Length;
    }
    private void OpenPath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); }
        catch (Exception exception) { _status.Text = "无法打开：" + exception.Message; }
    }
    private string? ResultDirectory => _result is null
        ?string.IsNullOrWhiteSpace(_captureResult?.SnapshotFile)?null:Path.GetDirectoryName(_captureResult.SnapshotFile)
        :string.IsNullOrWhiteSpace(_result.Path)?_result.RunDir:_result.Path;
    public void OpenTutorial()
    {
        if (_tutorial is null)
        {
            _tutorial = new TutorialWindow(); _tutorial.Closed += (_, _) => _tutorial = null; _tutorial.Show(this);
        }
        else _tutorial.Activate();
    }

    private static string SettingsPath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CODNameFinder", "settings.json");
    private void LoadSettings()
    {
        try
        {
            if (!File.Exists(SettingsPath)) return;
            var settings = JsonSerializer.Deserialize(File.ReadAllText(SettingsPath), AppJsonContext.Default.WindowSettings);
            if (settings is not null)
            {
                ApplyConfiguration(settings.ToConfig());
                if(settings.CordycepDirectory is not null)_cordycepDirectory.Text=settings.CordycepDirectory;
                RefreshCaptureScripts(explicitSelection:settings.CordycepScript);
            }
        }
        catch (Exception exception) { AppendLog("偏好设置无法读取，使用默认值：" + exception.Message); }
    }
    private void SaveSettings(Config config)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(SettingsPath)!); var temporary = SettingsPath + ".tmp";
            var settings=WindowSettings.From(config);settings.CordycepDirectory=_cordycepDirectory.Text?.Trim()??"";
            settings.CordycepScript=Selected(_cordycepScript);
            File.WriteAllText(temporary, JsonSerializer.Serialize(settings, AppJsonContext.Default.WindowSettings));
            File.Move(temporary, SettingsPath, true);
        }
        catch (Exception exception) { AppendLog("偏好设置未保存：" + exception.Message); }
    }

    public async Task Capture(string path, bool tutorial)
    {
        if (tutorial) OpenTutorial();
        await Task.Delay(450);
        Window visual = tutorial ? _tutorial! : this;
        if (!tutorial && Program.ValidationMode && (Environment.GetCommandLineArgs().Contains("--advanced")||Environment.GetCommandLineArgs().Contains("--capture")||Environment.GetCommandLineArgs().Contains("--upstream")))
        { _inputScroll.Offset = new Vector(0, _inputScroll.Extent.Height); await Task.Delay(150); }
        // Avalonia's immediate renderer can double-scale nested rounded panels
        // when a live 2x window is rendered to a 192-DPI offscreen bitmap. Keep
        // validation artifacts in logical pixels; production DPI stays native.
        var size = new PixelSize(Math.Max(1, (int)Math.Ceiling(visual.Bounds.Width)), Math.Max(1, (int)Math.Ceiling(visual.Bounds.Height)));
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        using var bitmap = new RenderTargetBitmap(size, new Vector(96, 96)); bitmap.Render(visual); bitmap.Save(path, PngBitmapEncoderOptions.Default);
        var state = new GuiCaptureState
        {
            SinglePage = true, AlgorithmDropdown = _profile.Items.Count == HashProfiles.All.Count, AssetTypeDropdown = _assetType.Items.Count == AssetNames.Labels.Count + 1,UpstreamContribution=UpstreamState(),InteractiveControlsCentered=InteractiveControlsCentered(),ControlAlignmentIssues=ControlAlignmentIssues(),
            InputModeDropdown=_inputMode.Items.Count==2,InputMode=Selected(_inputMode),SnapshotFilePicker=true,CordycepCaptureControls=true,
            CordycepCaptureEnabled=_attachCapture.IsEnabled&&_launchCapture.IsEnabled,
            BatDropdown=true,SelectedScript=Selected(_cordycepScript),BatCount=_cordycepScript.Items.Count,
            DomainDropdown = _domain.Items.Count > 1, AdvancedOptions = true, CommunityDefaultOff = _community.IsChecked != true,
            NewCsvButton = true, TutorialOpen = tutorial, TutorialLoaded = tutorial &&
                (_tutorial!.MarkdownText.Contains("一键计算并导出", StringComparison.Ordinal) || _tutorial.MarkdownText.Contains("确认计算并导出", StringComparison.Ordinal)),
            CrossAssetCheckbox = true, RelatedFolderPicker = true, CrossAssetDefaultEnabled = _crossAsset.IsChecked == true,
            Framework = "Avalonia", NativeAot = !RuntimeFeature.IsDynamicCodeSupported, Width = visual.Bounds.Width, Height = visual.Bounds.Height,
            RenderScaling = visual.RenderScaling, CaptureDpi = 96,
            IconPresent = visual.Icon is not null,
            Style = "liquid-glass", GlassPanels = visual.GetVisualDescendants().OfType<Control>().Count(control => control.Classes.Contains("glass-panel")),
            SystemTransparency = visual.ActualTransparencyLevel.ToString(),
            Glass = GlassEffects.Snapshot(visual),
            CompactHeader = _chrome is { } chrome && chrome.Surface.Bounds.Height is > 0 and <= 52 && chrome.Title.FontSize <= 16,
            IntroductionRemoved = IntroductionRemoved(), CustomTitlebar = ExtendClientAreaToDecorationsHint && WindowDecorations == WindowDecorations.BorderOnly,
            TitlebarHeight = _chrome?.Surface.Bounds.Height ?? 0, WindowButtons = _chrome?.WindowButtonNames() ?? [],
            ActionsVisible = ActionsWithinWindow(), InputViewportHeight = _inputScroll.Viewport.Height, LogHeight = _log.Bounds.Height,
            InputsScrollable = _inputScroll.Extent.Height > _inputScroll.Viewport.Height + 1,
            WorkerAvailable = File.Exists(Path.Combine(AppContext.BaseDirectory, "engine", "NameFinder.Engine.exe"))
        };
        var json = JsonSerializer.Serialize(state, AppJsonContext.Default.GuiCaptureState); File.WriteAllText(path + ".json", json); Console.WriteLine(json);
    }

    public void WriteRunValidationState()
    {
        var state = new GuiRunValidationState
        {
            NativeAot = !RuntimeFeature.IsDynamicCodeSupported, ProgressEvents = _progressEvents,UpstreamContribution=UpstreamState(),InteractiveControlsCentered=InteractiveControlsCentered(),ControlAlignmentIssues=ControlAlignmentIssues(),
            InputModeDropdown=_inputMode.Items.Count==2,InputMode=Selected(_inputMode),SnapshotFile=_snapshotFile.Text??"",
            SnapshotFilePicker=true,CordycepCaptureControls=true,CaptureComplete=_captureResult?.Complete??false,
            BatDropdown=true,SelectedScript=Selected(_cordycepScript),BatCount=_cordycepScript.Items.Count,
            CaptureStatus=_captureResult?.Status??"",CaptureRecords=_captureResult?.Records??0,CaptureStrings=_captureResult?.Strings??0,
            EstimateAvailable = EstimateAvailable, ConfirmationRequired = EstimateAvailable && _estimateConfiguration is not null,
            EstimateTargetCount = _estimate?.TargetCount ?? 0, EstimateCandidateTotal = _estimate?.CandidateTotal ?? 0,
            DomainDropdown = _domain.Items.Count > 1, HashDomain = Selected(_domain), DomainStatus = SelectedDomain?.Status ?? "manual",
            ProfileId = Selected(_profile), AdvancedOptions = true, CommunityEnabled = _community.IsChecked == true,
            IconPresent = Icon is not null,
            Style = "liquid-glass", GlassPanels = this.GetVisualDescendants().OfType<Control>().Count(control => control.Classes.Contains("glass-panel")),
            SystemTransparency = ActualTransparencyLevel.ToString(),
            Glass = GlassEffects.Snapshot(this),
            CompactHeader = _chrome is { } chrome && chrome.Surface.Bounds.Height is > 0 and <= 52 && chrome.Title.FontSize <= 16,
            IntroductionRemoved = IntroductionRemoved(), CustomTitlebar = ExtendClientAreaToDecorationsHint && WindowDecorations == WindowDecorations.BorderOnly,
            TitlebarHeight = _chrome?.Surface.Bounds.Height ?? 0, WindowButtons = _chrome?.WindowButtonNames() ?? [],
            ActionsVisible = ActionsWithinWindow(), InputViewportHeight = _inputScroll.Viewport.Height, LogHeight = _log.Bounds.Height,
            StartButtonEnabled = _start.IsEnabled, StopButtonEnabled = _stop.IsEnabled,
            ResultButtonEnabled = _openResult.IsEnabled, CsvButtonEnabled = _openCsv.IsEnabled,
            StoppedByRequest = _stopTriggered, Status = ValidationStatusText,
            CrossAssetAvailable = _crossAsset.IsEnabled, RelatedFolderEnabled = _relatedFolder.IsEnabled
        };
        using var stream = new MemoryStream(); using var writer = new Utf8JsonWriter(stream);
        JsonSerializer.Serialize(writer, state, AppJsonContext.Default.GuiRunValidationState); writer.Flush(); Console.WriteLine(Encoding.UTF8.GetString(stream.ToArray()));
    }
    private bool IntroductionRemoved() => !this.GetVisualDescendants().OfType<TextBlock>().Any(text =>
        text.Text == "资产名称计算与验证 · 导出 Saluki 名称增量" || text.Text == "COD Name Finder" && text.FontSize > 16);

    private bool ActionsWithinWindow() => new[] { _start, _stop, _openResult, _openCsv }.All(button =>
    {
        var corner = button.TranslatePoint(new Point(), this);
        return corner is { } point && button.Bounds.Width > 0 && button.Bounds.Height >= 40
            && point.X >= 0 && point.Y >= 0 && point.X + button.Bounds.Width <= Bounds.Width + 1
            && point.Y + button.Bounds.Height <= Bounds.Height + 1;
    });
}

internal sealed class WindowSettings
{
    public string InputMode {get;set;}="folder";
    public string SnapshotFile {get;set;}="";
    public string? CordycepDirectory {get;set;}
    public string? CordycepScript {get;set;}
    public string Folder { get; set; } = "";
    public string Indexes { get; set; } = "";
    public string Output { get; set; } = "";
    public string Profile { get; set; } = "iw-resource63";
    public string AssetType { get; set; } = "xanim";
    public string Game { get; set; } = "COD2026";
    public string Dictionary { get; set; } = "";
    public string Keyword { get; set; } = "";
    public string Backend { get; set; } = "auto";
    public string RelatedFolder { get; set; } = "";
    public bool ExcludeMaterial { get; set; } = true;
    public bool Low60 { get; set; }
    public bool CrossAsset { get; set; } = true;
    public long Budget { get; set; } = 10000000;
    public int Seconds { get; set; } = 7200;
    public int NumberMax { get; set; } = 32;
    public string HashDomain { get; set; } = "";
    public bool AllowUnverifiedDomain { get; set; }
    public string BorrowedDictionary { get; set; } = "";
    public bool Community { get; set; }
    public string CommunityCache { get; set; } = "";
    public bool CommunityRefresh { get; set; }
    public bool Anyway { get; set; }
    public Config ToConfig() => new()
    {
        InputMode=InputMode,SnapshotFile=SnapshotFile,
        Folder = Folder, Indexes = Indexes, Output = Output, Profile = Profile, AssetType = AssetType, Game = Game,
        Dictionary = Dictionary, Keyword = Keyword, Backend = Backend, RelatedFolder = RelatedFolder,
        ExcludeMaterial = ExcludeMaterial, Low60 = Low60, CrossAsset = CrossAsset, Budget = Budget, Seconds = Seconds,
        NumberMax = NumberMax, HashDomain = HashDomain, AllowUnverifiedDomain = AllowUnverifiedDomain,
        BorrowedDictionary = BorrowedDictionary, Community = Community, CommunityCache = CommunityCache,
        CommunityRefresh = CommunityRefresh, Anyway = Anyway
    };
    public static WindowSettings From(Config config) => new()
    {
        InputMode=config.InputMode,SnapshotFile=config.SnapshotFile,
        Folder = config.Folder, Indexes = config.Indexes, Output = config.Output, Profile = config.Profile,
        AssetType = config.AssetType, Game = config.Game, Dictionary = config.Dictionary, Keyword = config.Keyword,
        Backend = config.Backend, RelatedFolder = config.RelatedFolder, ExcludeMaterial = config.ExcludeMaterial,
        Low60 = config.Low60, CrossAsset = config.CrossAsset, Budget = config.Budget, Seconds = config.Seconds,
        NumberMax = config.NumberMax, HashDomain = config.HashDomain, AllowUnverifiedDomain = config.AllowUnverifiedDomain,
        BorrowedDictionary = config.BorrowedDictionary, Community = config.Community, CommunityCache = config.CommunityCache,
        CommunityRefresh = config.CommunityRefresh, Anyway = config.Anyway
    };
}

internal sealed class GuiCaptureState
{
    [JsonPropertyName("control_alignment_issues")] public string[] ControlAlignmentIssues {get;set;}=[];
    [JsonPropertyName("interactive_controls_centered")] public bool InteractiveControlsCentered {get;set;}
    [JsonPropertyName("upstream_contribution")] public GuiUpstreamState UpstreamContribution {get;set;}=new();
    [JsonPropertyName("compact_header")] public bool CompactHeader { get; set; }
    [JsonPropertyName("introduction_removed")] public bool IntroductionRemoved { get; set; }
    [JsonPropertyName("custom_titlebar")] public bool CustomTitlebar { get; set; }
    [JsonPropertyName("titlebar_height")] public double TitlebarHeight { get; set; }
    [JsonPropertyName("window_buttons")] public string[] WindowButtons { get; set; } = [];
    [JsonPropertyName("input_mode_dropdown")] public bool InputModeDropdown {get;set;}
    [JsonPropertyName("input_mode")] public string InputMode {get;set;}="folder";
    [JsonPropertyName("snapshot_file_picker")] public bool SnapshotFilePicker {get;set;}
    [JsonPropertyName("cordycep_capture_controls")] public bool CordycepCaptureControls {get;set;}
    [JsonPropertyName("cordycep_capture_enabled")] public bool CordycepCaptureEnabled {get;set;}
    [JsonPropertyName("bat_dropdown")] public bool BatDropdown {get;set;}
    [JsonPropertyName("selected_script")] public string SelectedScript {get;set;}="";
    [JsonPropertyName("bat_count")] public int BatCount {get;set;}
    [JsonPropertyName("render_scaling")] public double RenderScaling { get; set; }
    [JsonPropertyName("capture_dpi")] public double CaptureDpi { get; set; }
    [JsonPropertyName("domain_dropdown")] public bool DomainDropdown { get; set; }
    [JsonPropertyName("advanced_options")] public bool AdvancedOptions { get; set; }
    [JsonPropertyName("community_default_off")] public bool CommunityDefaultOff { get; set; }
    [JsonPropertyName("actions_visible")] public bool ActionsVisible { get; set; }
    [JsonPropertyName("input_viewport_height")] public double InputViewportHeight { get; set; }
    [JsonPropertyName("log_height")] public double LogHeight { get; set; }
    [JsonPropertyName("glass")] public GlassRenderingState Glass { get; set; } = new();
    [JsonPropertyName("style")] public string Style { get; set; } = "liquid-glass";
    [JsonPropertyName("glass_panels")] public int GlassPanels { get; set; }
    [JsonPropertyName("system_transparency")] public string SystemTransparency { get; set; } = "None";
    [JsonPropertyName("icon_present")] public bool IconPresent { get; set; }
    [JsonPropertyName("single_page")] public bool SinglePage { get; set; }
    [JsonPropertyName("algorithm_dropdown")] public bool AlgorithmDropdown { get; set; }
    [JsonPropertyName("asset_type_dropdown")] public bool AssetTypeDropdown { get; set; }
    [JsonPropertyName("new_csv_button")] public bool NewCsvButton { get; set; }
    [JsonPropertyName("tutorial_open")] public bool TutorialOpen { get; set; }
    [JsonPropertyName("tutorial_loaded")] public bool TutorialLoaded { get; set; }
    [JsonPropertyName("cross_asset_checkbox")] public bool CrossAssetCheckbox { get; set; }
    [JsonPropertyName("related_folder_picker")] public bool RelatedFolderPicker { get; set; }
    [JsonPropertyName("cross_asset_default_enabled")] public bool CrossAssetDefaultEnabled { get; set; }
    [JsonPropertyName("framework")] public string Framework { get; set; } = "Avalonia";
    [JsonPropertyName("native_aot")] public bool NativeAot { get; set; }
    [JsonPropertyName("width")] public double Width { get; set; }
    [JsonPropertyName("height")] public double Height { get; set; }
    [JsonPropertyName("inputs_scrollable")] public bool InputsScrollable { get; set; }
    [JsonPropertyName("worker_available")] public bool WorkerAvailable { get; set; }
}

internal sealed class GuiRunValidationState
{
    [JsonPropertyName("control_alignment_issues")] public string[] ControlAlignmentIssues {get;set;}=[];
    [JsonPropertyName("interactive_controls_centered")] public bool InteractiveControlsCentered {get;set;}
    [JsonPropertyName("upstream_contribution")] public GuiUpstreamState UpstreamContribution {get;set;}=new();
    [JsonPropertyName("compact_header")] public bool CompactHeader { get; set; }
    [JsonPropertyName("introduction_removed")] public bool IntroductionRemoved { get; set; }
    [JsonPropertyName("custom_titlebar")] public bool CustomTitlebar { get; set; }
    [JsonPropertyName("titlebar_height")] public double TitlebarHeight { get; set; }
    [JsonPropertyName("window_buttons")] public string[] WindowButtons { get; set; } = [];
    [JsonPropertyName("input_mode_dropdown")] public bool InputModeDropdown {get;set;}
    [JsonPropertyName("input_mode")] public string InputMode {get;set;}="folder";
    [JsonPropertyName("snapshot_file")] public string SnapshotFile {get;set;}="";
    [JsonPropertyName("snapshot_file_picker")] public bool SnapshotFilePicker {get;set;}
    [JsonPropertyName("cordycep_capture_controls")] public bool CordycepCaptureControls {get;set;}
    [JsonPropertyName("bat_dropdown")] public bool BatDropdown {get;set;}
    [JsonPropertyName("selected_script")] public string SelectedScript {get;set;}="";
    [JsonPropertyName("bat_count")] public int BatCount {get;set;}
    [JsonPropertyName("capture_complete")] public bool CaptureComplete {get;set;}
    [JsonPropertyName("capture_status")] public string CaptureStatus {get;set;}="";
    [JsonPropertyName("capture_records")] public long CaptureRecords {get;set;}
    [JsonPropertyName("capture_strings")] public long CaptureStrings {get;set;}
    [JsonPropertyName("estimate_available")] public bool EstimateAvailable { get; set; }
    [JsonPropertyName("confirmation_required")] public bool ConfirmationRequired { get; set; }
    [JsonPropertyName("estimate_target_count")] public long EstimateTargetCount { get; set; }
    [JsonPropertyName("estimate_candidate_total")] public long EstimateCandidateTotal { get; set; }
    [JsonPropertyName("domain_dropdown")] public bool DomainDropdown { get; set; }
    [JsonPropertyName("hash_domain")] public string HashDomain { get; set; } = "";
    [JsonPropertyName("domain_status")] public string DomainStatus { get; set; } = "";
    [JsonPropertyName("profile_id")] public string ProfileId { get; set; } = "";
    [JsonPropertyName("advanced_options")] public bool AdvancedOptions { get; set; }
    [JsonPropertyName("community_enabled")] public bool CommunityEnabled { get; set; }
    [JsonPropertyName("actions_visible")] public bool ActionsVisible { get; set; }
    [JsonPropertyName("input_viewport_height")] public double InputViewportHeight { get; set; }
    [JsonPropertyName("log_height")] public double LogHeight { get; set; }
    [JsonPropertyName("glass")] public GlassRenderingState Glass { get; set; } = new();
    [JsonPropertyName("style")] public string Style { get; set; } = "liquid-glass";
    [JsonPropertyName("glass_panels")] public int GlassPanels { get; set; }
    [JsonPropertyName("system_transparency")] public string SystemTransparency { get; set; } = "None";
    [JsonPropertyName("icon_present")] public bool IconPresent { get; set; }
    [JsonPropertyName("event")] public string Event { get; set; } = "gui_validation";
    [JsonPropertyName("framework")] public string Framework { get; set; } = "Avalonia";
    [JsonPropertyName("native_aot")] public bool NativeAot { get; set; }
    [JsonPropertyName("progress_events")] public long ProgressEvents { get; set; }
    [JsonPropertyName("start_button_enabled")] public bool StartButtonEnabled { get; set; }
    [JsonPropertyName("stop_button_enabled")] public bool StopButtonEnabled { get; set; }
    [JsonPropertyName("result_button_enabled")] public bool ResultButtonEnabled { get; set; }
    [JsonPropertyName("csv_button_enabled")] public bool CsvButtonEnabled { get; set; }
    [JsonPropertyName("stopped_by_request")] public bool StoppedByRequest { get; set; }
    [JsonPropertyName("status")] public string Status { get; set; } = "";
    [JsonPropertyName("cross_asset_available")] public bool CrossAssetAvailable { get; set; }
    [JsonPropertyName("related_folder_enabled")] public bool RelatedFolderEnabled { get; set; }
}

[JsonSourceGenerationOptions(WriteIndented = true)]
[JsonSerializable(typeof(WindowSettings))]
[JsonSerializable(typeof(GuiCaptureState))]
[JsonSerializable(typeof(GuiRunValidationState))]
[JsonSerializable(typeof(GlassRenderingState))]
[JsonSerializable(typeof(GuiUpstreamState))]
internal partial class AppJsonContext : JsonSerializerContext { }
