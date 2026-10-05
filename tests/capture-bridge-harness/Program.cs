using CODNameFinder.Core;
using System.Text;
using System.Text.Json;

var root=Path.GetFullPath(args[0]);Directory.CreateDirectory(root);var directory=Path.Combine(root,"Cordycep 中文目录");Directory.CreateDirectory(directory);
foreach(var filename in new[]{"RunMW7Beta.bat","RunBO7.bat","自选 Beta 加载.bat","uppercase.BAT"})File.WriteAllText(Path.Combine(directory,filename),"@echo off");
File.WriteAllText(Path.Combine(directory,"ignore.cmd"),"@echo off");
Directory.CreateDirectory(Path.Combine(directory,"child"));File.WriteAllText(Path.Combine(directory,"child","nested.bat"),"@echo off");
var scripts=CordycepScripts.Enumerate(directory);
if(scripts.Length!=4||scripts.Contains("nested.bat")||scripts.Contains("ignore.cmd")||!scripts.Contains("uppercase.BAT"))throw new InvalidOperationException("BAT root enumeration mismatch");
if(CordycepScripts.Select(scripts,"COD2026")!="RunMW7Beta.bat"||CordycepScripts.Select(scripts,"BO7")!="RunBO7.bat")throw new InvalidOperationException("game default BAT selection mismatch");
if(CordycepScripts.Select(scripts,"BO7","自选 Beta 加载.bat")!="自选 Beta 加载.bat")throw new InvalidOperationException("BAT refresh lost user selection");
var indexes=Path.Combine(root,"indexes");Directory.CreateDirectory(indexes);var sources=Path.Combine(root,"snapshots");Directory.CreateDirectory(sources);
var snapshot=Path.Combine(sources,"快照.json");File.WriteAllText(snapshot,"{}");
var config=new Config{InputMode="snapshot",SnapshotFile=snapshot,Folder="",Indexes=indexes,Output=Path.Combine(root,"names")};
config.Validate();var checks=CoreSelfTests.Run();var progress=0;
var attached=Pipeline.Capture(directory,"COD2026",Path.Combine(root,"attached"),progress:(_,_)=>progress++,script:"自选 Beta 加载.bat");
if(!attached.Complete||attached.Records!=42||attached.Strings!=8||attached.Additional!["launch"].GetBoolean()||attached.Additional["script"].GetString()!="")throw new InvalidOperationException("attachment report mismatch");
var launched=Pipeline.Capture(directory,"BO7",Path.Combine(root,"launched"),true,script:"自选 Beta 加载.bat");
if(!launched.Complete||!launched.Additional!["launch"].GetBoolean()||launched.Additional["load_all"].GetBoolean()||launched.Additional["script"].GetString()!="自选 Beta 加载.bat")throw new InvalidOperationException("launch flags mismatch");
var defaultLaunch=Pipeline.Capture(directory,"BO7",Path.Combine(root,"default-launch"),true);
if(defaultLaunch.Additional!["script"].GetString()!="")throw new InvalidOperationException("existing capture caller compatibility mismatch");
var badScriptRejected=false;try{Pipeline.Capture(directory,"BO7",Path.Combine(root,"bad-script"),true,script:"..\\outside.bat");}catch(ArgumentException){badScriptRejected=true;}
if(!badScriptRejected)throw new InvalidOperationException("outside-root launch BAT was accepted");
using var cancellation=new CancellationTokenSource();
var partial=Pipeline.Capture(directory,"COD2026",Path.Combine(root,"cancelled"),progress:(_,_)=>cancellation.Cancel(),cancellation:cancellation.Token);
if(partial.Complete||partial.Status!="partial"||!File.Exists(partial.SnapshotFile))throw new InvalidOperationException("cancel did not save partial manifest");
var quoted=Pipeline.Estimate(config);var result=Pipeline.Run(config);
if(quoted.Status!="estimated"||result.Entries!=2)throw new InvalidOperationException("snapshot run/estimate bridge mismatch");
var rejected=false;try{new Config{InputMode="snapshot",SnapshotFile=snapshot,Indexes=indexes,Output=Path.Combine(sources,"inside")}.Validate();}catch(ArgumentException){rejected=true;}
if(!rejected)throw new InvalidOperationException("output inside source snapshot was accepted");
using var bytes=new MemoryStream();using(var writer=new Utf8JsonWriter(bytes))
{
    writer.WriteStartObject();writer.WriteBoolean("passed",true);writer.WriteBoolean("protocol_stub",true);writer.WriteNumber("core_self_checks",checks);
    writer.WriteNumber("progress_events",progress);writer.WriteBoolean("attach_without_load",true);writer.WriteBoolean("launch_selected_bat_without_load_all",true);
    writer.WriteBoolean("bat_root_enumeration",true);writer.WriteBoolean("bat_game_defaults",true);writer.WriteBoolean("bat_user_selection_preserved",true);writer.WriteBoolean("unicode_script_argument",true);writer.WriteBoolean("outside_root_script_rejected",badScriptRejected);
    writer.WriteBoolean("cancellation_saves_partial",true);writer.WriteBoolean("empty_folder_snapshot_bridge",true);writer.WriteBoolean("snapshot_output_isolation",rejected);
    writer.WriteString("partial_manifest",partial.SnapshotFile);writer.WriteEndObject();writer.Flush();
}
Console.WriteLine(Encoding.UTF8.GetString(bytes.ToArray()));
