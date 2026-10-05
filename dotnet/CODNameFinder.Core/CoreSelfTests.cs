using System.Text.Json;

namespace CODNameFinder.Core;

public static class CoreSelfTests
{
    public static int Run()
    {
        var count=0;
        void Check(bool condition,string name){if(!condition)throw new InvalidOperationException("自检失败："+name);count++;}
        Check(HashProfiles.All.Count==GeneratedRegistry.ProfileIds.Length&&HashProfiles.All.Count==20,"20 个注册表哈希规则");Check(AssetNames.Labels.Count==21,"21 种非模型资产 / 名称域类型");
        var config=new Config{Folder=@"D:\中文哈希",Indexes="indexes",Output="result",RelatedFolder="已命名模型",Backend="cpu",AssetType="xanim",CrossAsset=true};
        var json=JsonSerializer.Serialize(config,FinderJsonContext.Default.Config);
        Check(json.Contains("\"cross_asset\"",StringComparison.Ordinal)&&json.Contains("\"related_folder\"",StringComparison.Ordinal),"引擎 snake_case 协议");
        var parsed=JsonSerializer.Deserialize(json,FinderJsonContext.Default.Config)!;
        Check(parsed.Folder==config.Folder&&parsed.RelatedFolder==config.RelatedFolder&&parsed.CrossAsset,"配置 UTF-8 回读");
        var report=JsonSerializer.Deserialize("{\"status\":\"completed\",\"entries\":3,\"stages\":[{\"rule\":\"cross-asset\"}],\"cross_asset\":{\"enabled\":true}}",FinderJsonContext.Default.RunReport)!;
        var encoded=JsonSerializer.Serialize(report,FinderJsonContext.Default.RunReport);
        Check(encoded.Contains("\"stages\"",StringComparison.Ordinal)&&encoded.Contains("\"cross_asset\"",StringComparison.Ordinal),"完整报告保留未知字段");
        var evt=JsonSerializer.Deserialize("{\"event\":\"progress\",\"processed\":65536,\"message\":\"声音名称推测\"}",FinderJsonContext.Default.WorkerEvent)!;
        Check(evt.Processed==65536&&evt.Message=="声音名称推测","流式进度协议");
        Check(parsed.InputMode=="folder"&&parsed.SnapshotFile.Length==0,"旧配置默认文件夹输入");
        var snapshotConfig=JsonSerializer.Deserialize("{\"input_mode\":\"snapshot\",\"snapshot_file\":\"中文离线.json\",\"folder\":\"\"}",FinderJsonContext.Default.Config)!;
        Check(snapshotConfig.InputMode=="snapshot"&&snapshotConfig.SnapshotFile=="中文离线.json"&&snapshotConfig.Folder.Length==0,"离线快照配置协议");
        var captured=JsonSerializer.Deserialize("{\"event\":\"result\",\"result\":{\"status\":\"partial\",\"snapshot_file\":\"部分捕获.json\",\"records\":42,\"strings\":8,\"complete\":false,\"pid\":123,\"game\":\"COD2026\",\"future_metadata\":{\"valid\":true}}}",FinderJsonContext.Default.CaptureWorkerEvent)!;
        Check(captured.Result is {Records:42,Strings:8,Complete:false,ProcessId:123,Game:"COD2026"},"捕获计数与停止协议");
        Check(captured.Result!.Additional?.ContainsKey("future_metadata")==true,"捕获元数据保留");
        Check(CordycepScripts.DefaultForGame("COD2026")=="RunMW7Beta.bat"&&CordycepScripts.DefaultForGame("BO7")=="RunBO7.bat","作品对应默认 BAT");
        var scripts=new[]{"自选 Beta 加载.bat","RunBO7.bat","RunMW7Beta.bat"};
        Check(CordycepScripts.Select(scripts,"COD2026")=="RunMW7Beta.bat"&&CordycepScripts.Select(scripts,"BO7")=="RunBO7.bat","默认启动脚本选择");
        Check(CordycepScripts.Select(scripts,"COD2026","自选 Beta 加载.bat")=="自选 Beta 加载.bat"&&CordycepScripts.Select(scripts,"COD2026","runbo7.BAT")=="RunBO7.bat","刷新保留用户选择与文件名大小写");
        Check(CordycepScripts.Select([],"COD2026")==""&&CordycepScripts.Select(["中文 空格.bat"],"BO7")=="中文 空格.bat","空列表及非默认 BAT");
        var invalidScriptRejected=false;
        try{CordycepScripts.Validate(".","..\\RunBO7.bat");}catch(ArgumentException){invalidScriptRejected=true;}
        Check(invalidScriptRejected,"启动脚本限定目录根文件名");
        return count;
    }
}
