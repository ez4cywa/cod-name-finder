using System.Text;
using System.Text.Json;
using System.Runtime.CompilerServices;

namespace CODNameFinder.Core;

public static class Cli
{
    public static int? Dispatch(string[] args)
    {
        if(args.Length==0 || args[0] is not ("run" or "estimate" or "methods" or "table-audit" or "community" or "cordycep" or "devices" or "selftest" or "upstream"))return null;
        Console.OutputEncoding=new UTF8Encoding(false);Console.InputEncoding=new UTF8Encoding(false);
        string? folder=null;string? configFile=null;string? snapshotFile=null;
        try
        {
            if(args[0]=="upstream")
            {
                if(args.Length<2)throw new ArgumentException("用法：upstream <action> [--export <目录>] [--package <目录>] [--offline] --stdin");
                string? export=null;string? package=null;bool stdin=false;bool offline=false;
                for(var index=2;index<args.Length;index++)
                {
                    if(args[index]=="--stdin"){stdin=true;continue;}
                    if(args[index]=="--offline"){offline=true;continue;}
                    if(args[index] is not ("--export" or "--package")||index+1>=args.Length||args[index+1].StartsWith("--",StringComparison.Ordinal))
                        throw new ArgumentException("上游贡献仅接受 --export、--package、--offline 和 --stdin；凭据须通过标准输入传入");
                    if(args[index++]=="--export")export=args[index];else package=args[index];
                }
                if(!stdin&&!offline)throw new ArgumentException("上游贡献凭据须通过 --stdin JSON 传入");
                var credentials=stdin?JsonSerializer.Deserialize(Console.In.ReadToEnd(),UpstreamJsonContext.Default.UpstreamCredentials)
                    ??throw new ArgumentException("标准输入必须是凭据 JSON 对象"):new UpstreamCredentials();
                UpstreamSubmission.ExecuteAsync(args[1],export,package,credentials,protocol:Console.WriteLine,offline:offline).GetAwaiter().GetResult();
                return 0;
            }
            if(args[0] is "estimate" or "methods" or "table-audit" or "community" or "cordycep" || args[0]=="run" && (args.Contains("--estimate")||args.Contains("--anyway")))
            {
                string? temporaryConfig=null;
                try
                {
                    var forwarded=args.ToArray();
                    if(args[0] is "run" or "estimate")
                    {
                        var index=Array.FindIndex(forwarded,1,item=>!item.StartsWith("--",StringComparison.Ordinal));
                        if(index<0)throw new ArgumentException("请提供 config.json");
                        configFile=Path.GetFullPath(forwarded[index]);
                        var forwardedConfig=JsonSerializer.Deserialize(File.ReadAllText(configFile),FinderJsonContext.Default.Config)??throw new ArgumentException("运行配置必须是 JSON 对象");
                        folder=forwardedConfig.InputMode=="folder"?forwardedConfig.Folder:null;
                        snapshotFile=forwardedConfig.InputMode=="snapshot"?forwardedConfig.SnapshotFile:null;
                        Pipeline.ResolvePaths(forwardedConfig);
                        temporaryConfig=Path.Combine(Path.GetTempPath(),"namefinder-cli-"+Guid.NewGuid().ToString("N")+".json");
                        File.WriteAllText(temporaryConfig,JsonSerializer.Serialize(forwardedConfig,FinderJsonContext.Default.Config),new UTF8Encoding(false));
                        forwarded[index]=temporaryConfig;
                        var control=Array.IndexOf(forwarded,"--control");if(control>=0&&control+1<forwarded.Length)forwarded[control+1]=Path.GetFullPath(forwarded[control+1]);
                    }
                    else if(args[0]=="cordycep")
                    {
                        foreach(var option in new[]{"--directory","--output","--control"})
                        {
                            var index=Array.IndexOf(forwarded,option);
                            if(index<0)continue;
                            if(index+1>=forwarded.Length||forwarded[index+1].StartsWith("--",StringComparison.Ordinal))throw new ArgumentException("缺少 "+option+" 路径");
                            forwarded[index+1]=Path.GetFullPath(forwarded[index+1]);
                        }
                    }
                    else
                    {
                        var pathIndex=args[0]=="table-audit"?1:2;
                        if(pathIndex<forwarded.Length)forwarded[pathIndex]=Path.GetFullPath(forwarded[pathIndex]);
                        var outputIndex=Array.IndexOf(forwarded,"--output");if(outputIndex>=0&&outputIndex+1<forwarded.Length)forwarded[outputIndex+1]=Path.GetFullPath(forwarded[outputIndex+1]);
                    }
                    using var process=Pipeline.StartEngine(forwarded);
                    var errors=Pipeline.DrainAsync(process.StandardError);
                    while(process.StandardOutput.ReadLine() is { } line)Console.WriteLine(line);
                    process.WaitForExit();var diagnostics=errors.GetAwaiter().GetResult();
                    if(!string.IsNullOrWhiteSpace(diagnostics))Console.Error.WriteLine(diagnostics);
                    return process.ExitCode;
                }
                finally {if(temporaryConfig is not null&&File.Exists(temporaryConfig))File.Delete(temporaryConfig);}
            }
            if(args[0]=="selftest")
            {
                if(args.Length!=1)throw new ArgumentException("selftest 不接受其他参数");
                using var bytes=new MemoryStream();
                using(var writer=new Utf8JsonWriter(bytes))
                {
                    writer.WriteStartObject();
                    writer.WriteBoolean("native_aot",!RuntimeFeature.IsDynamicCodeSupported);
                    writer.WriteNumber("checks",CoreSelfTests.Run());
                    writer.WriteString("version",AppVersion.Version);
                    writer.WriteEndObject();
                }
                Console.WriteLine(Encoding.UTF8.GetString(bytes.ToArray()));return 0;
            }
            if(args[0]=="devices")
            {
                if(args.Length!=1)throw new ArgumentException("devices 不接受其他参数");
                using var process=Pipeline.StartEngine(["devices"]);
                var error=Pipeline.DrainAsync(process.StandardError);
                while(process.StandardOutput.ReadLine() is { } line)Console.WriteLine(line);
                process.WaitForExit();var text=error.GetAwaiter().GetResult();
                if(process.ExitCode!=0)throw new InvalidOperationException("设备查询失败："+text);
                return 0;
            }
            if(args.Length is not (2 or 4) || (args.Length==4 && args[2]!="--control"))throw new ArgumentException("用法：run <config.json> [--control <control.txt>]");
            configFile=Path.GetFullPath(args[1]);
            var config=JsonSerializer.Deserialize(File.ReadAllText(args[1],new UTF8Encoding(false,true)),FinderJsonContext.Default.Config)??throw new ArgumentException("运行配置必须是 JSON 对象");
            folder=config.InputMode=="folder"?config.Folder:null;snapshotFile=config.InputMode=="snapshot"?config.SnapshotFile:null;bool errorWritten=false;
            try
            {
                Pipeline.RunCore(config,null,default,args.Length==4?args[3]:null,line=>
                {
                    using var doc=JsonDocument.Parse(line);
                    if(doc.RootElement.TryGetProperty("event",out var evt)&&evt.GetString()=="error")
                    {
                        errorWritten=true;
                        using var bytes=new MemoryStream();
                        using(var writer=new Utf8JsonWriter(bytes))
                        {
                            writer.WriteStartObject();
                            foreach(var property in doc.RootElement.EnumerateObject())
                            {
                                if(property.NameEquals("config_file"))continue;
                                property.WriteTo(writer);
                            }
                            writer.WriteString("config_file",configFile);
                            writer.WriteEndObject();
                        }
                        Console.WriteLine(Encoding.UTF8.GetString(bytes.ToArray()));
                    }
                    else Console.WriteLine(line);
                });
                return 0;
            }
            catch when(errorWritten) {return 2;}
        }
        catch(Exception error)
        {
            var message=error switch {JsonException=>"配置文件不是有效 JSON",DecoderFallbackException=>"输入文本不是有效 UTF-8，请重新保存为 UTF-8 编码",_=>error.Message};
            using var bytes=new MemoryStream();
            using(var writer=new Utf8JsonWriter(bytes))
            {
                writer.WriteStartObject();writer.WriteString("event","error");writer.WriteString("type",error.GetType().Name);
                writer.WriteString("message",message);writer.WriteString("command",args[0]);
                if(configFile is not null)writer.WriteString("config_file",configFile);
                if(folder is not null)writer.WriteString("input_folder",folder);
                if(snapshotFile is not null)writer.WriteString("snapshot_file",snapshotFile);
                writer.WriteEndObject();
            }
            Console.WriteLine(Encoding.UTF8.GetString(bytes.ToArray()));
            return 2;
        }
    }
}
