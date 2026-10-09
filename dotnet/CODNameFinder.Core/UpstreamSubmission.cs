using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CODNameFinder.Core;

public sealed class UpstreamCredentials
{
    [JsonPropertyName("token")] public string Token {get;set;}="";
    [JsonPropertyName("remember_token")] public bool RememberToken {get;set;}
}

public sealed class UpstreamReport
{
    [JsonPropertyName("status")] public string Status {get;set;}="";
    [JsonPropertyName("authenticated")] public bool Authenticated {get;set;}
    [JsonPropertyName("login")] public string Login {get;set;}="";
    [JsonPropertyName("credential_saved")] public bool CredentialSaved {get;set;}
    [JsonPropertyName("package_dir")] public string PackageDirectory {get;set;}="";
    [JsonPropertyName("preview_path")] public string PreviewPath {get;set;}="";
    [JsonPropertyName("title")] public string Title {get;set;}="";
    [JsonPropertyName("body")] public string Body {get;set;}="";
    [JsonPropertyName("eligible_count")] public int EligibleCount {get;set;}
    [JsonPropertyName("excluded_count")] public int ExcludedCount {get;set;}
    [JsonPropertyName("unsupported_count")] public int UnsupportedCount {get;set;}
    [JsonPropertyName("submitted_count")] public int SubmittedCount {get;set;}
    [JsonPropertyName("game")] public string Game {get;set;}="";
    [JsonPropertyName("network_checked")] public bool NetworkChecked {get;set;}
    [JsonPropertyName("submit_allowed")] public bool SubmitAllowed {get;set;}
    [JsonPropertyName("pull_request_url")] public string PullRequestUrl {get;set;}="";
}

public sealed record UpstreamPreview(string Text,string Path,bool Truncated);

/// <summary>Secret-bearing input stays on stdin; the bundled engine owns GitHub and Windows credentials.</summary>
public static class UpstreamSubmission
{
    public const string Repository="https://github.com/KingslayerKyle/hash-slinging-slasher";
    public static bool ShouldAutoSubmit(RunReport? result,bool low60,bool enabled)
        => enabled&&!low60&&result is {Status:"completed",Entries:>0};

    public static UpstreamPreview ReadPreview(UpstreamReport report,int maxCharacters=65536)
    {
        if(maxCharacters is <1 or >65536)throw new ArgumentOutOfRangeException(nameof(maxCharacters));
        if(string.IsNullOrWhiteSpace(report.PreviewPath))
        {
            if(report.Status=="ready")throw new InvalidDataException("未收到包含全部公开名称的预览文件，请重新预览。");
            return new(report.Title+Environment.NewLine+Environment.NewLine+report.Body,"",false);
        }
        if(!Path.IsPathFullyQualified(report.PreviewPath)||!Path.GetExtension(report.PreviewPath).Equals(".md",StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("完整预览须为本地 Markdown 文件。");
        var path=Path.GetFullPath(report.PreviewPath);
        using var reader=new StreamReader(path,new UTF8Encoding(false,true),detectEncodingFromByteOrderMarks:false);
        var buffer=new char[maxCharacters+1];var count=reader.ReadBlock(buffer,0,buffer.Length);
        var truncated=count>maxCharacters;
        if(truncated){count=maxCharacters;if(char.IsHighSurrogate(buffer[count-1]))count--;}
        return new(new string(buffer,0,count).TrimStart('\uFEFF'),path,truncated);
    }

    public static bool TryGetPullRequestUri(string? value,out Uri? uri)
    {
        uri=null;
        if(!Uri.TryCreate(value,UriKind.Absolute,out var parsed)||parsed.Scheme!="https"||
           !parsed.Host.Equals("github.com",StringComparison.OrdinalIgnoreCase)||!parsed.IsDefaultPort||
           parsed.UserInfo.Length>0||parsed.Query.Length>0||parsed.Fragment.Length>0)return false;
        var parts=parsed.AbsolutePath.Split('/',StringSplitOptions.RemoveEmptyEntries);
        if(parts.Length!=4||!parts[0].Equals("KingslayerKyle",StringComparison.OrdinalIgnoreCase)||
           !parts[1].Equals("hash-slinging-slasher",StringComparison.OrdinalIgnoreCase)||parts[2]!="pull"||
           !long.TryParse(parts[3],out var number)||number<1)return false;
        uri=parsed;return true;
    }

    public static Task<UpstreamReport> ExecuteAsync(string action,string? export=null,string? package=null,
        UpstreamCredentials? credentials=null,Action<string>? progress=null,CancellationToken cancellation=default,
        Action<string>? protocol=null,bool offline=false)
    {
        if(action is not ("auth-status" or "auth-save" or "auth-clear" or "prepare" or "submit"))
            throw new ArgumentException("不支持的上游名称贡献操作");
        if(offline&&action!="prepare")throw new ArgumentException("--offline 仅适用于 prepare");
        if(action=="prepare"&&string.IsNullOrWhiteSpace(export))throw new ArgumentException("请选择本次导出的结果目录");
        if(action=="submit"&&string.IsNullOrWhiteSpace(export)&&string.IsNullOrWhiteSpace(package))throw new ArgumentException("请先预览本次提交");
        var arguments=new List<string>{"upstream",action};
        if(!string.IsNullOrWhiteSpace(export)){arguments.Add("--export");arguments.Add(Path.GetFullPath(export));}
        if(!string.IsNullOrWhiteSpace(package)){arguments.Add("--package");arguments.Add(Path.GetFullPath(package));}
        arguments.Add("--stdin");
        if(offline)arguments.Add("--offline");
        var input=offline?new UpstreamCredentials():credentials??new UpstreamCredentials();
        input.Token??="";
        if(input.Token.Length>4096||input.Token.IndexOfAny(['\r','\n','\0'])>=0)throw new ArgumentException("GitHub token 格式无效");
        return ExecuteCoreAsync(arguments,input,progress,cancellation,protocol);
    }

    private static async Task<UpstreamReport> ExecuteCoreAsync(IEnumerable<string> arguments,UpstreamCredentials credentials,
        Action<string>? progress,CancellationToken cancellation,Action<string>? protocol)
    {
        cancellation.ThrowIfCancellationRequested();
        using var process=Pipeline.StartEngine(arguments,redirectInput:true);
        using var registration=cancellation.Register(()=>Kill(process));
        var errors=Pipeline.DrainAsync(process.StandardError);
        string? failure=null;UpstreamReport? result=null;var tail=new Queue<string>();
        try
        {
            await process.StandardInput.WriteAsync(JsonSerializer.Serialize(credentials,UpstreamJsonContext.Default.UpstreamCredentials).AsMemory(),cancellation).ConfigureAwait(false);
            await process.StandardInput.FlushAsync(cancellation).ConfigureAwait(false);
            process.StandardInput.Close();
            while(await process.StandardOutput.ReadLineAsync(cancellation).ConfigureAwait(false) is { } raw)
            {
                if(string.IsNullOrWhiteSpace(raw))continue;
                var line=Redact(raw,credentials.Token);
                using JsonDocument document=ParseProtocol(line);
                var root=document.RootElement;
                if(root.ValueKind!=JsonValueKind.Object)throw new InvalidDataException("名称贡献引擎返回了无效响应");
                var eventName=root.TryGetProperty("event",out var evt)?evt.GetString():null;
                if(eventName=="progress")
                {
                    var message=root.TryGetProperty("message",out var item)?item.GetString()??"":"";
                    progress?.Invoke(message);
                }
                else if(eventName=="error")failure=root.TryGetProperty("message",out var message)?message.GetString():"名称贡献失败";
                else if(eventName is null)
                    result=JsonSerializer.Deserialize(root,UpstreamJsonContext.Default.UpstreamReport);
                else if(eventName=="result"&&root.TryGetProperty("result",out var payload))
                    result=JsonSerializer.Deserialize(payload,UpstreamJsonContext.Default.UpstreamReport);
                else {tail.Enqueue(line.Length>1000?line[..1000]:line);if(tail.Count>3)tail.Dequeue();}
                protocol?.Invoke(line);
            }
            await process.WaitForExitAsync(cancellation).ConfigureAwait(false);
            var diagnostics=Redact(await errors.ConfigureAwait(false),credentials.Token);
            cancellation.ThrowIfCancellationRequested();
            if(failure is not null)throw new InvalidOperationException(failure);
            if(process.ExitCode!=0||result is null)
                throw new InvalidOperationException($"上游名称贡献失败（退出码 {process.ExitCode}）。"+
                    (string.IsNullOrWhiteSpace(diagnostics)?"":"\n"+diagnostics.Trim())+
                    (tail.Count==0?"":"\n"+string.Join("\n",tail)));
            if(result.EligibleCount<0||result.ExcludedCount<0||result.UnsupportedCount<0||result.SubmittedCount<0)
                throw new InvalidDataException("名称贡献引擎返回了无效数量");
            result.Status??="";result.Login??="";result.PackageDirectory??="";result.PreviewPath??="";
            result.Title??="";result.Body??="";result.Game??="";result.PullRequestUrl??="";
            if(result.PullRequestUrl.Length>0&&!TryGetPullRequestUri(result.PullRequestUrl,out _))
                throw new InvalidDataException("名称贡献引擎返回的 PR 地址不属于固定上游仓库");
            return result;
        }
        catch(Exception exception) when(exception is not OperationCanceledException)
        {
            // Do not include an unsanitized process/JSON exception in UI logs.
            throw new InvalidOperationException(Redact(exception.Message,credentials.Token));
        }
        finally
        {
            Kill(process);
            try {await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5)).ConfigureAwait(false);}catch(TimeoutException){}
            try {await errors.WaitAsync(TimeSpan.FromSeconds(5)).ConfigureAwait(false);}catch(TimeoutException){}catch(IOException){}
        }
    }

    private static JsonDocument ParseProtocol(string line)
    {
        try {return JsonDocument.Parse(line);}
        catch(JsonException){throw new InvalidDataException("名称贡献引擎返回了无效 JSON");}
    }
    private static void Kill(Process process)
    {
        try {if(!process.HasExited)process.Kill(entireProcessTree:true);}
        catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}
    }
    internal static string Redact(string text,string token)
    {
        if(token.Length==0)return text;
        return text.Replace(token,"[redacted]",StringComparison.Ordinal)
            .Replace(JsonEncodedText.Encode(token).ToString(),"[redacted]",StringComparison.OrdinalIgnoreCase);
    }
}

[JsonSerializable(typeof(UpstreamCredentials))]
[JsonSerializable(typeof(UpstreamReport))]
[JsonSourceGenerationOptions(GenerationMode=JsonSourceGenerationMode.Metadata)]
public partial class UpstreamJsonContext : JsonSerializerContext { }
