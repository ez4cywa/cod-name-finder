using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace CODNameFinder.Core;

/// <summary>AOT-safe process boundary; the packaged Python engine owns business rules.</summary>
public static class Pipeline
{
    public static string EnginePath
    {
        get
        {
            var configured=Environment.GetEnvironmentVariable("COD_NAME_FINDER_ENGINE");
            return string.IsNullOrWhiteSpace(configured)?Path.Combine(AppContext.BaseDirectory,"engine","NameFinder.Engine.exe"):Path.GetFullPath(configured);
        }
    }
    public static RunReport Run(Config config,Action<long,string>? progress=null,CancellationToken cancellation=default)
        => RunCore(config,progress,cancellation,null,null);

    public static CaptureReport Capture(string directory,string game,string output,bool launch=false,
        Action<long,string>? progress=null,CancellationToken cancellation=default,string? script=null)
    {
        if(string.IsNullOrWhiteSpace(directory)||!Directory.Exists(directory))throw new ArgumentException("请选择存在的 Cordycep 目录");
        if(game is not ("BO7" or "COD2026"))throw new ArgumentException("Cordycep 捕获当前支持 BO7 或 COD2026，请先选择对应作品");
        if(string.IsNullOrWhiteSpace(output))throw new ArgumentException("请选择捕获快照的输出目录");
        directory=Path.GetFullPath(directory);output=Path.GetFullPath(output);
        if(launch&&!string.IsNullOrEmpty(script))CordycepScripts.Validate(directory,script);
        var temporary=Path.Combine(Path.GetTempPath(),"cod-name-finder-capture-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);var control=Path.Combine(temporary,"control.txt");
        try
        {
            WriteControl(control,cancellation.IsCancellationRequested?"pause":"run");
            var stopSaved=0;var stopWarningShown=false;
            using var registration=cancellation.Register(()=>{if(TryStop(control))Interlocked.Exchange(ref stopSaved,1);});
            var arguments=new List<string>{"cordycep","capture","--directory",directory,"--game",game,"--output",output,"--control",control};
            if(launch)
            {
                arguments.Add("--launch");
                if(!string.IsNullOrEmpty(script)){arguments.Add("--script");arguments.Add(script);}
            }
            using var process=StartEngine(arguments);var stderr=DrainAsync(process.StandardError);
            CaptureReport? result=null;string? failure=null;var tail=new Queue<string>();
            try
            {
                while(process.StandardOutput.ReadLine() is { } line)
                {
                    if(string.IsNullOrWhiteSpace(line))continue;
                    CaptureWorkerEvent? item=null;
                    try {item=JsonSerializer.Deserialize(line,FinderJsonContext.Default.CaptureWorkerEvent);}
                    catch(JsonException){AddTail(tail,line);}
                    if(item is null)continue;
                    if(item.Event=="progress")progress?.Invoke(item.Processed,item.Message);
                    else if(item.Event=="result")result=item.Result;
                    else if(item.Event=="error")failure=item.Message;
                    if(cancellation.IsCancellationRequested&&Volatile.Read(ref stopSaved)==0)
                    {
                        if(TryStop(control))Interlocked.Exchange(ref stopSaved,1);
                        else if(!stopWarningShown)
                        {stopWarningShown=true;progress?.Invoke(item.Processed,"停止捕获请求暂未写入控制文件，正在重试；请等待排查报告保存。");}
                    }
                }
            }
            catch
            {
                TryStop(control);process.StandardOutput.ReadToEnd();process.WaitForExit();stderr.GetAwaiter().GetResult();throw;
            }
            process.WaitForExit();var diagnostics=stderr.GetAwaiter().GetResult();
            if(failure is not null)throw new InvalidOperationException(failure+"\nCordycep 目录："+directory);
            if(process.ExitCode!=0||result is null)
            {
                var message=$"捕获进程没有成功返回快照（退出码 {process.ExitCode}）。";
                if(tail.Count>0)message+="\n"+string.Join("\n",tail);
                if(!string.IsNullOrWhiteSpace(diagnostics))message+="\n"+diagnostics.Trim();
                throw new InvalidOperationException(message);
            }
            if(result.Game!=game)throw new InvalidOperationException("捕获报告中的作品与所选作品不一致，请核对实例。");
            if(result.Records<0||result.Strings<0)throw new InvalidOperationException("捕获报告中的数量无效。");
            if(result.Complete&&result.Status!="completed")throw new InvalidOperationException("捕获报告中的完成状态不一致。");
            if(!string.IsNullOrEmpty(result.SnapshotFile))result.SnapshotFile=Path.GetFullPath(result.SnapshotFile,Path.GetDirectoryName(EnginePath)!);
            if(result.Complete&&(string.IsNullOrEmpty(result.SnapshotFile)||!File.Exists(result.SnapshotFile)))
                throw new InvalidOperationException("捕获报告称已完成，但快照文件不存在。");
            return result;
        }
        finally {try {Directory.Delete(temporary,true);}catch(IOException){}catch(UnauthorizedAccessException){}}
    }

    public static string SyncCommunity(Config config,CancellationToken cancellation=default)
    {
        var cache=string.IsNullOrEmpty(config.CommunityCache)?Path.Combine(Path.GetFullPath(config.Output),".community-cache"):Path.GetFullPath(config.CommunityCache);
        var args=new List<string>{"community","sync",cache};if(config.CommunityRefresh)args.Add("--refresh");
        using var process=StartEngine(args);
        // Downloads only publish complete cache snapshots; stopping the
        // process leaves the previous committed snapshot available.
        using var registration=cancellation.Register(()=>{try {if(!process.HasExited)process.Kill(true);}catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}});
        var error=DrainAsync(process.StandardError);var output=process.StandardOutput.ReadToEnd();process.WaitForExit();var diagnostics=error.GetAwaiter().GetResult();
        cancellation.ThrowIfCancellationRequested();
        if(process.ExitCode!=0)throw new InvalidOperationException("社区词典同步失败："+output+diagnostics);
        return output;
    }

    public static EstimateReport Estimate(Config config,Action<long,string>? progress=null,CancellationToken cancellation=default)
    {
        config.Validate();
        var temporary=Path.Combine(Path.GetTempPath(),"cod-name-finder-quote-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(temporary);
        var control=Path.Combine(temporary,"control.txt");
        try
        {
            var configPath=Path.Combine(temporary,"config.json");
            // Both calls use the GUI's working directory for relative inputs.
            var copy=JsonSerializer.Deserialize(JsonSerializer.Serialize(config,FinderJsonContext.Default.Config),FinderJsonContext.Default.Config)!;
            ResolvePaths(copy);
            File.WriteAllText(configPath,JsonSerializer.Serialize(copy,FinderJsonContext.Default.Config),new UTF8Encoding(false));
            WriteControl(control,cancellation.IsCancellationRequested?"pause":"run");
            using var registration=cancellation.Register(()=>TryStop(control));
            using var process=StartEngine(["estimate",configPath,"--control",control]);
            var stderr=DrainAsync(process.StandardError);EstimateReport? result=null;string? failure=null;
            while(process.StandardOutput.ReadLine() is { } line)
            {
                using var doc=JsonDocument.Parse(line);var root=doc.RootElement;
                if(!root.TryGetProperty("event",out var evt))continue;
                if(evt.GetString()=="progress")progress?.Invoke(root.GetProperty("processed").GetInt64(),root.GetProperty("message").GetString()??"");
                else if(evt.GetString()=="estimate")result=JsonSerializer.Deserialize(root.GetProperty("estimate"),FinderJsonContext.Default.EstimateReport);
                else if(evt.GetString()=="error")failure=root.GetProperty("message").GetString();
            }
            process.WaitForExit();var diagnostics=stderr.GetAwaiter().GetResult();
            if(failure is not null)throw new InvalidOperationException(WithInput(failure,config));
            if(process.ExitCode!=0||result is null)throw new InvalidOperationException("计划估算失败："+diagnostics);
            return result;
        }
        finally {try {Directory.Delete(temporary,true);}catch(IOException){}catch(UnauthorizedAccessException){}}
    }

    internal static void ResolvePaths(Config config)
    {
        if(!string.IsNullOrEmpty(config.Folder))config.Folder=Path.GetFullPath(config.Folder);
        if(!string.IsNullOrEmpty(config.SnapshotFile))config.SnapshotFile=Path.GetFullPath(config.SnapshotFile);
        config.Indexes=Path.GetFullPath(config.Indexes);config.Output=Path.GetFullPath(config.Output);
        if(!string.IsNullOrEmpty(config.Dictionary))config.Dictionary=Path.GetFullPath(config.Dictionary);
        if(!string.IsNullOrEmpty(config.BorrowedDictionary))config.BorrowedDictionary=Path.GetFullPath(config.BorrowedDictionary);
        if(!string.IsNullOrEmpty(config.CommunityCache))config.CommunityCache=Path.GetFullPath(config.CommunityCache);
        if(!string.IsNullOrEmpty(config.RelatedFolder))config.RelatedFolder=Path.GetFullPath(config.RelatedFolder);
    }

    internal static RunReport RunCore(Config config,Action<long,string>? progress,CancellationToken cancellation,string? inheritedControl,Action<string>? protocol)
    {
        config.Validate();
        // Relative paths belong to the calling GUI/CLI, not the engine directory.
        config=JsonSerializer.Deserialize(JsonSerializer.Serialize(config,FinderJsonContext.Default.Config),FinderJsonContext.Default.Config)!;
        ResolvePaths(config);
        var temporary=Path.Combine(Path.GetTempPath(),"cod-name-finder-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        var control=inheritedControl is null?Path.Combine(temporary,"control.txt"):Path.GetFullPath(inheritedControl);
        try
        {
            var configPath=Path.Combine(temporary,"config.json");
            File.WriteAllText(configPath,JsonSerializer.Serialize(config,FinderJsonContext.Default.Config),new UTF8Encoding(false));
            if(inheritedControl is null)WriteControl(control,cancellation.IsCancellationRequested?"pause":"run");
            else if(!File.Exists(control))throw new ArgumentException("控制文件不存在："+control);
            var stopSaved=0;var stopWarningShown=false;
            using var registration=cancellation.Register(()=>
            {
                if(TryStop(control))Interlocked.Exchange(ref stopSaved,1);
            });
            using var process=StartEngine(["run",configPath,"--control",control]);
            var stderr=DrainAsync(process.StandardError);
            RunReport? result=null; string? failure=null;
            var tail=new Queue<string>();
            try
            {
                while(process.StandardOutput.ReadLine() is { } line)
                {
                    if(string.IsNullOrWhiteSpace(line))continue;
                    WorkerEvent? item=null;
                    try { item=JsonSerializer.Deserialize(line,FinderJsonContext.Default.WorkerEvent); }
                    catch(JsonException) { AddTail(tail,line); }
                    if(item is null)continue;
                    protocol?.Invoke(line);
                    if(item.Event=="progress")progress?.Invoke(item.Processed,item.Message);
                    else if(item.Event=="result")result=item.Result;
                    else if(item.Event=="error")failure=WithInput(item.Message,config);
                    if(cancellation.IsCancellationRequested&&Volatile.Read(ref stopSaved)==0)
                    {
                        if(TryStop(control))Interlocked.Exchange(ref stopSaved,1);
                        else if(!stopWarningShown)
                        {
                            stopWarningShown=true;
                            progress?.Invoke(item.Processed,"停止请求暂未写入控制文件，正在重试；当前计算继续保存结果。");
                        }
                    }
                }
            }
            catch
            {
                TryStop(control);
                // Callback failure must still allow the worker to commit and export safely.
                process.StandardOutput.ReadToEnd();process.WaitForExit();stderr.GetAwaiter().GetResult();throw;
            }
            process.WaitForExit();var errorText=stderr.GetAwaiter().GetResult();
            if(cancellation.IsCancellationRequested&&Volatile.Read(ref stopSaved)==0)
                progress?.Invoke(result?.Processed??0,"停止请求未能写入控制文件；后台进程已自然结束，请检查临时目录权限。");
            if(failure is not null)throw new InvalidOperationException(failure);
            if(process.ExitCode!=0||result is null)
            {
                var message=process.ExitCode!=0?$"查找进程退出异常（退出码 {process.ExitCode}）。":"查找进程没有返回结果。";
                if(tail.Count>0)message+="\n"+string.Join("\n",tail);
                if(!string.IsNullOrWhiteSpace(errorText))message+="\n"+errorText.Trim();
                throw new InvalidOperationException(WithInput(message,config));
            }
            return result;
        }
        finally
        {
            try {Directory.Delete(temporary,true);}catch(IOException){}catch(UnauthorizedAccessException){}
        }
    }
    internal static Process StartEngine(IEnumerable<string> arguments,bool redirectInput=false)
    {
        var engine=EnginePath;
        if(!File.Exists(engine))throw new FileNotFoundException("软件计算引擎缺失，请重新安装完整安装包。",engine);
        var start=new ProcessStartInfo(engine)
        {
            UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,RedirectStandardInput=redirectInput,
            StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8,WorkingDirectory=Path.GetDirectoryName(engine)!
        };
        if(redirectInput)start.StandardInputEncoding=new UTF8Encoding(false);
        foreach(var argument in arguments)start.ArgumentList.Add(argument);
        start.Environment["PYTHONIOENCODING"]="utf-8";start.Environment["PYTHONUTF8"]="1";
        return Process.Start(start)??throw new InvalidOperationException("无法启动软件计算引擎");
    }
    internal static async Task<string> DrainAsync(StreamReader reader)
    {
        // Drain all bytes even after the retained diagnostic limit is reached.
        var retained=new StringBuilder();var buffer=new char[4096];int read;
        while((read=await reader.ReadAsync(buffer.AsMemory()).ConfigureAwait(false))>0)
        {
            retained.Append(buffer,0,read);
            if(retained.Length>16384)retained.Remove(0,retained.Length-16384);
        }
        return retained.ToString();
    }
    internal static void WriteControl(string path,string state)
    {
        var staging=path+"."+Guid.NewGuid().ToString("N")+".tmp";
        try {File.WriteAllText(staging,state,new UTF8Encoding(false));File.Move(staging,path,true);}
        finally {if(File.Exists(staging))File.Delete(staging);}
    }
    private static bool TryStop(string path)
    {
        // Windows MoveFile replacement can report ERROR_ACCESS_DENIED for a
        // sharing read lock, which .NET maps to UnauthorizedAccessException.
        // Bound both error classes to 95 ms; persistent permission denial still
        // returns false and is reported through the existing progress warning.
        for(var attempt=0;attempt<20;attempt++)
        {
            try {WriteControl(path,"pause");return true;}
            catch(IOException) {if(attempt<19)Thread.Sleep(5);}
            catch(UnauthorizedAccessException) {if(attempt<19)Thread.Sleep(5);}
        }
        return false;
    }
    private static void AddTail(Queue<string> tail,string line) {tail.Enqueue(line.Length>2000?line[..2000]:line);if(tail.Count>5)tail.Dequeue();}
    internal static string WithFolder(string message,string folder)=>message.Contains(folder,StringComparison.Ordinal)?message:message+"\n哈希文件夹："+folder;
    internal static string WithInput(string message,Config config)=>config.InputMode=="snapshot"
        ?message.Contains(config.SnapshotFile,StringComparison.Ordinal)?message:message+"\n离线快照："+config.SnapshotFile
        :WithFolder(message,config.Folder);
}
