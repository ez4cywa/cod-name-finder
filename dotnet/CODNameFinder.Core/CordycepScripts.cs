namespace CODNameFinder.Core;

/// <summary>Lists local launch scripts without executing or interpreting their contents.</summary>
public static class CordycepScripts
{
    public static string DefaultForGame(string game) => game switch
    {
        "COD2026" => "RunMW7Beta.bat",
        "BO7" => "RunBO7.bat",
        _ => ""
    };

    public static string[] Enumerate(string directory)
    {
        if(string.IsNullOrWhiteSpace(directory)||!Directory.Exists(directory))return [];
        return Directory.EnumerateFiles(directory,"*",SearchOption.TopDirectoryOnly)
            .Where(path=>Path.GetExtension(path).Equals(".bat",StringComparison.OrdinalIgnoreCase))
            .Select(Path.GetFileName).OfType<string>()
            .OrderBy(name=>name,StringComparer.OrdinalIgnoreCase).ToArray();
    }

    public static string Select(IReadOnlyList<string> scripts,string game,string? current=null)
    {
        var existing=scripts.FirstOrDefault(name=>name.Equals(current,StringComparison.OrdinalIgnoreCase));
        if(existing is not null)return existing;
        var preferred=DefaultForGame(game);
        return scripts.FirstOrDefault(name=>name.Equals(preferred,StringComparison.OrdinalIgnoreCase))??scripts.FirstOrDefault()??"";
    }

    public static string Validate(string directory,string script)
    {
        if(string.IsNullOrWhiteSpace(script)||Path.IsPathRooted(script)||Path.GetFileName(script)!=script
            ||script.Contains('/')||script.Contains('\\')||!Path.GetExtension(script).Equals(".bat",StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("请选择 Cordycep 目录里的 BAT 文件。");
        if(!File.Exists(Path.Combine(directory,script)))throw new ArgumentException("所选 BAT 文件已不存在，请刷新启动脚本列表。");
        return script;
    }
}
