using System.Text;
using System.Text.Json;

Console.OutputEncoding=new UTF8Encoding(false);
string Get(string name,string fallback=""){var i=Array.IndexOf(args,name);return i>=0&&i+1<args.Length?args[i+1]:fallback;}
void Write(Action<Utf8JsonWriter> action)
{
    using var bytes=new MemoryStream();using(var writer=new Utf8JsonWriter(bytes)){action(writer);writer.Flush();}
    Console.WriteLine(Encoding.UTF8.GetString(bytes.ToArray()));Console.Out.Flush();
}
if(args[0] is "run" or "estimate")
{
    using var config=JsonDocument.Parse(File.ReadAllText(args[1]));var root=config.RootElement;
    if(root.GetProperty("folder").GetString()!=""||root.GetProperty("input_mode").GetString()!="snapshot"||!Path.IsPathFullyQualified(root.GetProperty("snapshot_file").GetString()!))throw new InvalidOperationException("snapshot paths were not resolved independently of empty folder");
    if(args[0]=="estimate")Write(w=>{w.WriteStartObject();w.WriteString("event","estimate");w.WritePropertyName("estimate");w.WriteStartObject();w.WriteString("status","estimated");w.WriteNumber("target_count",2);w.WriteNumber("candidate_total",200);w.WriteNumber("budgeted_candidates",200);w.WriteEndObject();w.WriteEndObject();});
    else Write(w=>{w.WriteStartObject();w.WriteString("event","result");w.WritePropertyName("result");w.WriteStartObject();w.WriteString("status","completed");w.WriteNumber("entries",2);w.WriteNumber("processed",200);w.WriteString("path",root.GetProperty("output").GetString());w.WriteEndObject();w.WriteEndObject();});
    return;
}
if(args[0]!="cordycep")throw new InvalidOperationException("unexpected command");
if(args[1]=="status")
{
    Write(w=>{w.WriteStartObject();w.WriteString("directory",Get("--directory"));w.WriteBoolean("protocol_stub",true);w.WriteEndObject();});return;
}
var directory=Get("--directory");var output=Get("--output");var control=Get("--control");var game=Get("--game");
if(!Path.IsPathFullyQualified(directory)||!Path.IsPathFullyQualified(output)||!Path.IsPathFullyQualified(control))throw new InvalidOperationException("capture args must be absolute");
Directory.CreateDirectory(output);
File.WriteAllText(Path.Combine(output,"capture-args.json"),JsonSerializer.Serialize(args));
Write(w=>{w.WriteStartObject();w.WriteString("event","progress");w.WriteNumber("processed",42);w.WriteString("message","已读资产与中文路径");w.WriteEndObject();});
var paused=false;
for(var i=0;i<40;i++){Thread.Sleep(5);if(File.ReadAllText(control).Trim()=="pause"){paused=true;break;}}
var snapshot=Path.Combine(output,paused?"partial-捕获.json":"complete-快照.json");File.WriteAllText(snapshot,"{\"complete\":"+(paused?"false":"true")+",\"assets\":[],\"strings\":[]}");
Write(w=>{w.WriteStartObject();w.WriteString("event","result");w.WritePropertyName("result");w.WriteStartObject();
    w.WriteString("status",paused?"partial":"completed");w.WriteString("snapshot_file",snapshot);w.WriteNumber("records",42);w.WriteNumber("strings",8);
    w.WriteBoolean("complete",!paused);w.WriteNumber("pid",Environment.ProcessId);w.WriteString("game",game);w.WriteString("message",paused?"停止后已保存排查报告":"完整捕获完成");
    w.WriteBoolean("protocol_stub",true);w.WriteBoolean("launch",args.Contains("--launch"));w.WriteBoolean("load_all",args.Contains("--load-all"));w.WriteString("script",Get("--script"));
    w.WriteEndObject();w.WriteEndObject();});
