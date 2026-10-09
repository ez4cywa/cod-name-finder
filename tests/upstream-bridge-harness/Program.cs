using System.Diagnostics;
using System.Text;
using System.Text.Json;
using CODNameFinder.Core;

if(args.Length>0&&args[0]=="--cli")return Cli.Dispatch(args[1..])??99;
var root=Path.GetFullPath(args[0]);Directory.CreateDirectory(root);
var token="ghp_FAKE_测试_secret_123";
var credentials=new UpstreamCredentials {Token=token,RememberToken=true};
var checks=0;
void Check(bool condition,string message){if(!condition)throw new InvalidOperationException(message);checks++;}
string Folder(string mode)=>Path.Combine(root,mode);
var progress=new List<string>();
var offline=await UpstreamSubmission.ExecuteAsync("prepare",Folder("离线中文目录"));
Check(offline.Status=="ready"&&offline.EligibleCount==2&&!offline.NetworkChecked&&!offline.SubmitAllowed,"offline preview contract");
var forcedOffline=await UpstreamSubmission.ExecuteAsync("prepare",Folder("明确离线"),credentials:credentials,offline:true);
Check(!forcedOffline.NetworkChecked&&!forcedOffline.SubmitAllowed,"explicit offline discards supplied credentials");
var invalidOffline=false;
try{await UpstreamSubmission.ExecuteAsync("submit",Folder("明确离线"),credentials:credentials,offline:true);}catch(ArgumentException){invalidOffline=true;}
Check(invalidOffline,"explicit offline rejects remote action");
var ready=await UpstreamSubmission.ExecuteAsync("prepare",Folder("中文目录"),credentials:credentials,progress:progress.Add);
Check(ready.NetworkChecked&&ready.SubmitAllowed&&ready.PackageDirectory.EndsWith("贡献包")&&ready.Title=="测试提交","UTF8 paths and credentials");
var preview=UpstreamSubmission.ReadPreview(ready);
Check(preview.Text.Contains("public_verified_name_exact",StringComparison.Ordinal)&&!ready.Body.Contains("public_verified_name_exact",StringComparison.Ordinal)&&!preview.Truncated,"exact public names from preview file");
File.WriteAllText(ready.PreviewPath,new string('名',65535)+"😀"+new string('字',5000),new UTF8Encoding(false));
var longPreview=UpstreamSubmission.ReadPreview(ready);
Check(longPreview.Truncated&&longPreview.Text.Length==65535&&!char.IsHighSurrogate(longPreview.Text[^1])&&longPreview.Path==ready.PreviewPath,"64K bounded preview preserves surrogate pairs and full document path");
File.WriteAllBytes(ready.PreviewPath,[0xff,0xfe,0x00]);var invalidPreview=false;
try{UpstreamSubmission.ReadPreview(ready);}catch(DecoderFallbackException){invalidPreview=true;}
Check(invalidPreview,"preview rejects non UTF8 document");
Check(progress.Count==1&&!progress[0].Contains(token,StringComparison.Ordinal)&&progress[0].Contains("[redacted]",StringComparison.Ordinal),"progress redaction");
var submitted=await UpstreamSubmission.ExecuteAsync("submit",Folder("中文目录"),ready.PackageDirectory,credentials);
Check(submitted.Status=="submitted"&&submitted.SubmittedCount==2,"submission result protocol");
foreach(var action in new[]{"auth-status","auth-save","auth-clear"})
{
    var auth=await UpstreamSubmission.ExecuteAsync(action,credentials:credentials);
    Check(auth.Authenticated==(action!="auth-clear")&&auth.CredentialSaved==(action=="auth-save"),action+" contract");
}
foreach(var mode in new[]{"error","stderr","malformed","negative","invalid-url"})
{
    var rejected=false;
    try {await UpstreamSubmission.ExecuteAsync(mode=="invalid-url"?"submit":"prepare",Folder(mode),credentials:credentials);}
    catch(InvalidOperationException exception)
    {rejected=true;Check(!exception.Message.Contains(token,StringComparison.Ordinal)&&!exception.Message.Contains("\\u6D4B",StringComparison.Ordinal),mode+" exception secret redaction");}
    Check(rejected,mode+" must fail");
}
Check((await UpstreamSubmission.ExecuteAsync("prepare",Folder("empty"))).Status=="empty","empty final response");
using(var cancellation=new CancellationTokenSource())
{
    var timer=Stopwatch.StartNew();var cancelled=false;
    try {await UpstreamSubmission.ExecuteAsync("prepare",Folder("cancel"),credentials:credentials,progress:message=>{if(message=="waiting")cancellation.Cancel();},cancellation:cancellation.Token);}
    catch(OperationCanceledException){cancelled=true;}
    Check(cancelled&&timer.Elapsed<TimeSpan.FromSeconds(5),"cancellation bounded process cleanup");
}
var callbackFailed=false;
try {await UpstreamSubmission.ExecuteAsync("prepare",Folder("callback"),credentials:credentials,progress:message=>{if(message=="waiting")throw new InvalidOperationException("callback failed");});}
catch(InvalidOperationException){callbackFailed=true;}
Check(callbackFailed,"callback failure escapes safely");
foreach(var mode in new[]{"cancel","callback"})
{
    var pid=int.Parse(File.ReadAllText(Path.Combine(Folder(mode),"pid.txt")));var alive=false;
    try {using var child=Process.GetProcessById(pid);alive=!child.HasExited;}catch(ArgumentException){}
    Check(!alive,mode+" left child process running");
}
var complete=new RunReport {Status="completed",Entries=1};
Check(UpstreamSubmission.ShouldAutoSubmit(complete,false,true),"eligible auto submission");
Check(!UpstreamSubmission.ShouldAutoSubmit(complete,false,false),"automatic submission opt-in");
Check(!UpstreamSubmission.ShouldAutoSubmit(complete,true,true),"low60 auto exclusion");
Check(!UpstreamSubmission.ShouldAutoSubmit(new RunReport{Status="partial",Entries=1},false,true),"partial auto exclusion");
Check(!UpstreamSubmission.ShouldAutoSubmit(new RunReport{Status="completed",Entries=0},false,true),"empty auto exclusion");
Check(!UpstreamSubmission.ShouldAutoSubmit(null,false,true),"missing run auto exclusion");
Check(UpstreamSubmission.TryGetPullRequestUri(submitted.PullRequestUrl,out _)&&!UpstreamSubmission.TryGetPullRequestUri("https://github.com/elsewhere/repo/pull/123",out _),"fixed upstream PR URL");
var start=new ProcessStartInfo(Environment.ProcessPath!) {RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,UseShellExecute=false,CreateNoWindow=true,StandardInputEncoding=new UTF8Encoding(false),StandardOutputEncoding=Encoding.UTF8};
foreach(var argument in new[]{"--cli","upstream","prepare","--export",Folder("CLI 中文目录"),"--stdin"})start.ArgumentList.Add(argument);
using(var child=Process.Start(start)!)
{
    await child.StandardInput.WriteAsync(JsonSerializer.Serialize(credentials,UpstreamJsonContext.Default.UpstreamCredentials));child.StandardInput.Close();
    var stderr=child.StandardError.ReadToEndAsync();var stdout=await child.StandardOutput.ReadToEndAsync();await child.WaitForExitAsync();
    using var final=JsonDocument.Parse(stdout.Split('\n',StringSplitOptions.RemoveEmptyEntries).Last());
    Check(child.ExitCode==0&&final.RootElement.GetProperty("title").GetString()=="测试提交"&&!stdout.Contains(token,StringComparison.Ordinal)&&!(await stderr).Contains(token,StringComparison.Ordinal),"public CLI stdin passthrough");
}
using var bytes=new MemoryStream();using(var writer=new Utf8JsonWriter(bytes))
{writer.WriteStartObject();writer.WriteBoolean("passed",true);writer.WriteBoolean("protocol_stub",true);writer.WriteBoolean("real_network",false);writer.WriteNumber("checks",checks);writer.WriteBoolean("stdin_credentials",true);writer.WriteBoolean("utf8",true);writer.WriteBoolean("secret_redaction",true);writer.WriteBoolean("cancel_cleanup",true);writer.WriteBoolean("auto_submission_gate",true);writer.WriteBoolean("cli_forwarding",true);writer.WriteEndObject();}
Console.WriteLine(Encoding.UTF8.GetString(bytes.ToArray()));return 0;
