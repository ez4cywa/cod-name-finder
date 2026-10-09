using System.Text;
using System.Text.Json;

Console.InputEncoding=new UTF8Encoding(false,true);Console.OutputEncoding=new UTF8Encoding(false);
if(args.Length<3||args[0]!="upstream"||!args.Contains("--stdin"))throw new InvalidOperationException("bad protocol arguments");
using var input=JsonDocument.Parse(Console.In.ReadToEnd());
var token=input.RootElement.GetProperty("token").GetString()??"";
var remember=input.RootElement.GetProperty("remember_token").GetBoolean();
if(args.Contains("--offline")&&(token.Length>0||remember))throw new InvalidOperationException("offline carried credentials");
if(token.Length>0&&args.Any(item=>item.Contains(token,StringComparison.Ordinal)))throw new InvalidOperationException("secret appeared in process arguments");
string Value(string option){var index=Array.IndexOf(args,option);return index<0?"":args[index+1];}
var export=Value("--export");var package=Value("--package");
if(export.Length>0&&!Path.IsPathFullyQualified(export)||package.Length>0&&!Path.IsPathFullyQualified(package))throw new InvalidOperationException("relative protocol path");
var mode=export.Length==0?"auth":Path.GetFileName(export);
void Emit(object value){Console.WriteLine(JsonSerializer.Serialize(value));Console.Out.Flush();}
Emit(new{ @event="progress",message="中文进度 "+token});
if(mode is "cancel" or "callback")
{
    Directory.CreateDirectory(export);File.WriteAllText(Path.Combine(export,"pid.txt"),Environment.ProcessId.ToString());
    Emit(new{@event="progress",message="waiting"});Thread.Sleep(20000);
}
if(mode=="error")
{Emit(new{@event="error",message="不能提交 "+token});Console.Error.WriteLine("stderr "+token);return 2;}
if(mode=="stderr") {Console.Error.WriteLine("stderr "+token);return 2;}
if(mode=="malformed"){Console.WriteLine("bad json "+token);return 2;}
if(args[1].StartsWith("auth-",StringComparison.Ordinal))
{Emit(new{authenticated=args[1]!="auth-clear"&&token.Length>0,login="测试用户",credential_saved=args[1]=="auth-save"&&remember});return 0;}
if(args[1]=="prepare")
{
    Directory.CreateDirectory(Path.Combine(export,"贡献包"));
    File.WriteAllText(Path.Combine(export,"贡献包","preview.md"),"# 测试提交\n\n验证后新增名称\n\n| hash | name |\n| --- | --- |\n| 123 | public_verified_name_exact |\n",new UTF8Encoding(false));
    Emit(new{status=mode=="empty"?"empty":"ready",package_dir=Path.Combine(export,"贡献包"),preview_path=Path.Combine(export,"贡献包","preview.md"),
        title="测试提交",body="验证后新增名称",eligible_count=mode=="negative"?-1:mode=="empty"?0:2,excluded_count=3,unsupported_count=1,game="COD2026",network_checked=token.Length>0,submit_allowed=token.Length>0});
    return 0;
}
Emit(new{status="submitted",pull_request_url=mode=="invalid-url"?"https://evil.example/pull/12":"https://github.com/KingslayerKyle/hash-slinging-slasher/pull/123",submitted_count=2,package_dir=package});
return 0;
