using System.Text.Json.Serialization;
using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using CODNameFinder.Core;

namespace CODNameFinder.App;

public partial class MainWindow
{
    private readonly Expander _upstreamOptions=new() {Header="上游名称贡献 · Hash Slinging Slasher",IsExpanded=false,HorizontalAlignment=HorizontalAlignment.Stretch,Background=Brushes.Transparent,BorderBrush=GlassTheme.Line};
    private readonly TextBox _upstreamToken=new() {PasswordChar='●',PlaceholderText="GitHub token；留空可使用已保存的 Windows 凭据",PlaceholderForeground=GlassTheme.Secondary};
    private readonly CheckBox _upstreamRemember=new() {Content="保存至 Windows 凭据管理器",IsChecked=false};
    private readonly CheckBox _upstreamAuto=new() {Content="完成后自动预览并创建 PR（仅本会话）",IsChecked=false};
    private readonly Button _upstreamAuth=ActionButton("检查登录");
    private readonly Button _upstreamSave=ActionButton("保存凭据",false);
    private readonly Button _upstreamClear=ActionButton("删除保存凭据");
    private readonly Button _upstreamPrepare=ActionButton("预览提交",false);
    private readonly Button _upstreamSubmit=ActionButton("创建上游 PR",false);
    private readonly Button _upstreamOpenPreview=ActionButton("打开完整预览",false);
    private readonly Button _upstreamOpen=ActionButton("打开 PR",false);
    private readonly TextBlock _upstreamHint=Body("只贡献本次新增且完整验证的名称；创建 PR 会将这些名称公开到 KingslayerKyle/hash-slinging-slasher。");
    private readonly TextBox _upstreamPreview=new() {IsReadOnly=true,AcceptsReturn=true,TextWrapping=TextWrapping.Wrap,Height=160,MinHeight=84,MaxHeight=200,IsVisible=false};
    private CancellationTokenSource? _upstreamCancellation;
    private bool _upstreamBusy;
    private bool _resultLow60;
    private UpstreamReport? _upstreamPrepared;
    private string _upstreamPullRequest="";
    private string _upstreamPreviewPath="";
    private bool _upstreamPreviewTruncated;

    private void BuildUpstreamControls()
    {
        var panel=new StackPanel {Spacing=8,Margin=new Thickness(0,8,0,4)};
        panel.Children.Add(_upstreamToken);
        panel.Children.Add(_upstreamRemember);
        panel.Children.Add(UpstreamButtons(_upstreamAuth,_upstreamSave,_upstreamClear));
        panel.Children.Add(_upstreamAuto);
        panel.Children.Add(UpstreamButtons(_upstreamPrepare,_upstreamOpenPreview,_upstreamSubmit,_upstreamOpen));
        _upstreamHint.FontSize=12;_upstreamHint.Classes.Add("secondary");panel.Children.Add(_upstreamHint);
        _upstreamPreview.Classes.Add("log");panel.Children.Add(_upstreamPreview);
        _upstreamOptions.Content=panel;FormRow("上游名称贡献",_upstreamOptions);
        AutomationProperties.SetName(_upstreamToken,"GitHub token（隐藏输入，仅内存或 Windows 凭据）");
        AutomationProperties.SetName(_upstreamPreview,"上游名称贡献预览");
        foreach(var button in new[]{_upstreamAuth,_upstreamSave,_upstreamClear,_upstreamPrepare,_upstreamOpenPreview,_upstreamSubmit,_upstreamOpen})
            AutomationProperties.SetName(button,(string?)button.Content??"");
        ToolTip.SetTip(_upstreamAuto,"本次会话勾选后，计算完整完成且有正式新增名称时自动向固定上游仓库创建 PR；停止、预算耗尽和低60位候选均不提交。");
        ToolTip.SetTip(_upstreamRemember,"凭据由计算引擎保存至当前 Windows 用户的凭据管理器，不写入软件设置或结果文件。");
        ToolTip.SetTip(_upstreamHint,"首版贡献动画、图像、材质、声音文件和声音别名，支持 BO4、BOCW、MWII、MWIII、BO6、BO7、COD2026；其他类型和作品保留在本地，并计入不支持项。创建 PR 前会重新检查上游已有名称。");
        _upstreamToken.TextChanged+=(_,_)=>UpdateUpstreamControls();
        _upstreamRemember.IsCheckedChanged+=(_,_)=>UpdateUpstreamControls();
        _upstreamAuth.Click+=async(_,_)=>await PerformUpstreamAsync("auth-status");
        _upstreamSave.Click+=async(_,_)=>await PerformUpstreamAsync("auth-save");
        _upstreamClear.Click+=async(_,_)=>await PerformUpstreamAsync("auth-clear");
        _upstreamPrepare.Click+=async(_,_)=>await PerformUpstreamAsync("prepare");
        _upstreamSubmit.Click+=async(_,_)=>await PerformUpstreamAsync("submit");
        _upstreamOpenPreview.Click+=(_,_)=>OpenPath(_upstreamPreviewPath);
        _upstreamOpen.Click+=(_,_)=>
        {
            if(UpstreamSubmission.TryGetPullRequestUri(_upstreamPullRequest,out var uri))OpenPath(uri!.AbsoluteUri);
        };
        if(Program.ValidationMode&&Environment.GetCommandLineArgs().Contains("--upstream"))_upstreamOptions.IsExpanded=true;
        UpdateUpstreamControls();
    }

    private static Grid UpstreamButtons(params Button[] buttons)
    {
        var row=new Grid {ColumnDefinitions=new ColumnDefinitions(string.Join(',',buttons.Select(_=>"*"))),ColumnSpacing=8};
        for(var index=0;index<buttons.Length;index++)
        {buttons[index].HorizontalAlignment=HorizontalAlignment.Stretch;Grid.SetColumn(buttons[index],index);row.Children.Add(buttons[index]);}
        return row;
    }
    private bool CanContribute=>UpstreamSubmission.ShouldAutoSubmit(_result,_resultLow60,enabled:true);
    private void UpdateUpstreamControls()
    {
        var idle=!IsBusy;
        _upstreamAuth.IsEnabled=_upstreamClear.IsEnabled=idle;
        _upstreamSave.IsEnabled=idle&&_upstreamRemember.IsChecked==true&&!string.IsNullOrWhiteSpace(_upstreamToken.Text);
        _upstreamPrepare.IsEnabled=idle&&CanContribute;
        _upstreamSubmit.IsEnabled=idle&&CanContribute&&_upstreamPrepared is {Status:"ready",EligibleCount:>0};
        _upstreamOpen.IsEnabled=UpstreamSubmission.TryGetPullRequestUri(_upstreamPullRequest,out _);
        _upstreamOpenPreview.IsEnabled=File.Exists(_upstreamPreviewPath);
        _upstreamToken.IsEnabled=_upstreamRemember.IsEnabled=_upstreamAuto.IsEnabled=idle;
    }
    private void ResetUpstreamResult(bool low60)
    {
        _resultLow60=low60;_upstreamPrepared=null;_upstreamPullRequest="";_upstreamPreviewPath="";_upstreamPreviewTruncated=false;
        _upstreamPreview.Text="";_upstreamPreview.IsVisible=false;UpdateUpstreamControls();
    }

    private async Task PerformUpstreamAsync(string action,bool automatic=false)
    {
        if(IsBusy)return;
        if(action is "prepare" or "submit"&&!CanContribute)return;
        if(action=="prepare"){_upstreamPrepared=null;_upstreamPreviewPath="";_upstreamPreviewTruncated=false;}
        var credentials=new UpstreamCredentials {Token=_upstreamToken.Text?.Trim()??"",RememberToken=_upstreamRemember.IsChecked==true};
        _upstreamBusy=true;_upstreamCancellation=new CancellationTokenSource();
        _inputGrid.IsEnabled=false;_start.IsEnabled=false;_stop.IsEnabled=true;UpdateUpstreamControls();
        try
        {
            var export=action is "prepare" or "submit"?ResultDirectory:null;
            var package=action=="submit"?_upstreamPrepared?.PackageDirectory:null;
            if(action=="auth-save")credentials.RememberToken=true;
            void Progress(string message)=>Dispatcher.UIThread.Post(()=>
            {
                _upstreamHint.Text=message;AppendLog("上游贡献 · "+message);
            });
            var report=await UpstreamSubmission.ExecuteAsync(action,export,package,credentials,Progress,_upstreamCancellation.Token);
            DisplayUpstreamReport(action,report);
            if(automatic&&report is {Status:"ready",EligibleCount:>0})
            {
                if(!report.SubmitAllowed)throw new InvalidOperationException("尚未登录 GitHub，已保存离线预览；请输入 token 或检查保存的凭据后创建 PR。");
                report=await UpstreamSubmission.ExecuteAsync("submit",export,report.PackageDirectory,credentials,Progress,_upstreamCancellation.Token);
                DisplayUpstreamReport("submit",report);
            }
        }
        catch(OperationCanceledException)
        {
            _upstreamHint.Text="贡献操作已停止；计算结果已保留。若提交已发送，可先预览或检查 GitHub PR 后重试。";
            AppendLog("上游贡献 · "+_upstreamHint.Text);
        }
        catch(Exception exception)
        {
            _upstreamHint.Text=(automatic?"自动贡献失败：":"贡献操作失败：")+exception.Message;
            AppendLog("上游贡献 · "+_upstreamHint.Text);
        }
        finally
        {
            // Contribution failures never replace the completed run or its output buttons/status.
            credentials.Token="";_upstreamBusy=false;_upstreamCancellation.Dispose();_upstreamCancellation=null;
            _inputGrid.IsEnabled=true;_start.IsEnabled=true;_stop.IsEnabled=false;UpdateInputControls();UpdateCaptureControls();UpdateRelatedControls();UpdateAdvancedControls();UpdateUpstreamControls();
            if(_closeAfterSave)Close();
        }
    }

    private void DisplayUpstreamReport(string action,UpstreamReport report)
    {
        if(action.StartsWith("auth-",StringComparison.Ordinal))
        {
            _upstreamHint.Text=action=="auth-clear"?"已删除当前 Windows 用户保存的上游凭据；本会话输入仍只保存在内存。":
                report.Authenticated?$"已登录 {report.Login} · {(report.CredentialSaved?"已保存 Windows 凭据":"仅本会话凭据")}":
                report.CredentialSaved?"Windows 凭据已保存；点击检查登录可验证账号。":"尚未登录；可留空进行离线预览。";
        }
        else if(action=="prepare")
        {
            var preview=ReadUpstreamPreview(report);
            _upstreamPrepared=report;
            _upstreamPreview.Text=preview;
            _upstreamPreview.IsVisible=true;
            _upstreamHint.Text=$"可贡献 {report.EligibleCount:N0} 项 · 上游已有 {report.ExcludedCount:N0} 项 · 不支持 {report.UnsupportedCount:N0} 项 · "+
                (report.NetworkChecked?"已检查上游重复项；创建时再次检查。":"离线预览；创建 PR 时联网检查并去重。");
            if(report.Status=="empty")_upstreamHint.Text="没有可贡献的新名称。"+_upstreamHint.Text;
            if(_upstreamPreviewTruncated)_upstreamHint.Text+=" 界面仅显示前 64K 字符，请打开完整预览查看全部名称。";
        }
        else
        {
            if(report.PullRequestUrl.Length>0)_upstreamPullRequest=report.PullRequestUrl;
            _upstreamHint.Text=report.Status switch
            {
                "submitted"=>$"已创建 PR · {report.SubmittedCount:N0} 个新增名称。",
                "already_submitted"=>"这些名称已提交，可点击打开 PR 查看。",
                "empty"=>"上游复查后没有可提交的新名称。",
                _=>"贡献操作完成："+report.Status
            };
            if(report.Status is "submitted" or "already_submitted" or "empty")_upstreamPrepared=null;
        }
        AppendLog("上游贡献 · "+_upstreamHint.Text);
        if(report.PullRequestUrl.Length>0)AppendLog("上游 PR："+report.PullRequestUrl);
    }
    private string ReadUpstreamPreview(UpstreamReport report)
    {
        var preview=UpstreamSubmission.ReadPreview(report);
        _upstreamPreviewTruncated=preview.Truncated;_upstreamPreviewPath=preview.Path;
        return preview.Truncated?preview.Text+Environment.NewLine+Environment.NewLine+"…界面预览已截断。点击‘打开完整预览’查看全部名称。":preview.Text;
    }
    private GuiUpstreamState UpstreamState()=>new()
    {
        Controls=_upstreamOptions.Content is not null,TokenMasked=_upstreamToken.PasswordChar!='\0',
        AutomaticEnabled=_upstreamAuto.IsChecked==true,RememberCredential=_upstreamRemember.IsChecked==true,
        SessionOnly=true,Busy=_upstreamBusy,PreviewEnabled=_upstreamPrepare.IsEnabled,
        SubmitEnabled=_upstreamSubmit.IsEnabled,OpenEnabled=_upstreamOpen.IsEnabled,
        FullPreviewEnabled=_upstreamOpenPreview.IsEnabled,PreviewTruncated=_upstreamPreviewTruncated
    };
}

internal sealed class GuiUpstreamState
{
    [JsonPropertyName("controls")] public bool Controls {get;set;}
    [JsonPropertyName("token_masked")] public bool TokenMasked {get;set;}
    [JsonPropertyName("automatic_enabled")] public bool AutomaticEnabled {get;set;}
    [JsonPropertyName("remember_credential")] public bool RememberCredential {get;set;}
    [JsonPropertyName("session_only")] public bool SessionOnly {get;set;}
    [JsonPropertyName("busy")] public bool Busy {get;set;}
    [JsonPropertyName("preview_enabled")] public bool PreviewEnabled {get;set;}
    [JsonPropertyName("submit_enabled")] public bool SubmitEnabled {get;set;}
    [JsonPropertyName("open_enabled")] public bool OpenEnabled {get;set;}
    [JsonPropertyName("full_preview_enabled")] public bool FullPreviewEnabled {get;set;}
    [JsonPropertyName("preview_truncated")] public bool PreviewTruncated {get;set;}
}
