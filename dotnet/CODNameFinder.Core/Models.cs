using System.Text.Json;
using System.Text.Json.Serialization;

namespace CODNameFinder.Core;

public static class AppVersion { public const string Version="2.4.0"; }

public sealed class Config
{
    [JsonPropertyName("input_mode")] public string InputMode {get;set;}="folder";
    [JsonPropertyName("snapshot_file")] public string SnapshotFile {get;set;}="";
    [JsonPropertyName("folder")] public string Folder {get;set;}="";
    [JsonPropertyName("indexes")] public string Indexes {get;set;}="";
    [JsonPropertyName("output")] public string Output {get;set;}="";
    [JsonPropertyName("profile")] public string Profile {get;set;}="iw-resource63";
    [JsonPropertyName("asset_type")] public string AssetType {get;set;}="xanim";
    [JsonPropertyName("game")] public string Game {get;set;}="COD2026";
    [JsonPropertyName("dictionary")] public string Dictionary {get;set;}="";
    [JsonPropertyName("keyword")] public string Keyword {get;set;}="";
    [JsonPropertyName("backend")] public string Backend {get;set;}="auto";
    [JsonPropertyName("exclude_material")] public bool ExcludeMaterial {get;set;}=true;
    [JsonPropertyName("low60")] public bool Low60 {get;set;}
    [JsonPropertyName("budget")] public long Budget {get;set;}=10_000_000;
    [JsonPropertyName("seconds")] public int Seconds {get;set;}=7200;
    [JsonPropertyName("number_max")] public int NumberMax {get;set;}=32;
    [JsonPropertyName("cross_asset")] public bool CrossAsset {get;set;}=true;
    [JsonPropertyName("related_folder")] public string RelatedFolder {get;set;}="";
    [JsonPropertyName("hash_domain")] public string HashDomain {get;set;}="";
    [JsonPropertyName("allow_unverified_domain")] public bool AllowUnverifiedDomain {get;set;}
    [JsonPropertyName("borrowed_dictionary")] public string BorrowedDictionary {get;set;}="";
    [JsonPropertyName("community")] public bool Community {get;set;}
    [JsonPropertyName("community_cache")] public string CommunityCache {get;set;}="";
    [JsonPropertyName("community_refresh")] public bool CommunityRefresh {get;set;}
    [JsonPropertyName("anyway")] public bool Anyway {get;set;}

    public Config Validate()
    {
        if(InputMode is not ("folder" or "snapshot"))throw new ArgumentException("请选择文件夹或离线快照输入来源");
        if(string.IsNullOrWhiteSpace(Indexes)||string.IsNullOrWhiteSpace(Output))
            throw new ArgumentException("请选择已有名称索引和输出目录");
        if(!HashProfiles.All.ContainsKey(Profile))throw new ArgumentException("请选择正确的哈希规则");
        if(AssetType!="auto"&&!AssetNames.Labels.ContainsKey(AssetType))throw new ArgumentException("请选择资产类型");
        if(Backend is not ("auto" or "cpu" or "gpu"))throw new ArgumentException("计算后端无效");
        if(Budget is <1 or >1_000_000_000)throw new ArgumentException("候选预算无效");
        if(Seconds is <1 or >86400)throw new ArgumentException("时间预算无效");
        if(NumberMax is <0 or >999)throw new ArgumentException("数字上限无效");
        string sourceDirectory;
        if(InputMode=="folder")
        {
            if(string.IsNullOrWhiteSpace(Folder)||!System.IO.Directory.Exists(Folder))throw new ArgumentException("请选择存在的哈希资产文件夹");
            sourceDirectory=Folder;
        }
        else
        {
            if(string.IsNullOrWhiteSpace(SnapshotFile)||!File.Exists(SnapshotFile))throw new ArgumentException("请选择存在的离线快照文件");
            if(Path.GetExtension(SnapshotFile).ToLowerInvariant() is not (".json" or ".ids"))throw new ArgumentException("离线快照须为 JSON 或 IDS 文件");
            sourceDirectory=Path.GetDirectoryName(Path.GetFullPath(SnapshotFile))!;
        }
        if(!System.IO.Directory.Exists(Indexes))throw new ArgumentException("已有名称索引文件夹不存在");
        if(IsWithin(Output,sourceDirectory)||IsWithin(Output,Indexes))throw new ArgumentException("输出目录请选择资产、快照和名称索引文件夹以外的位置");
        if(!string.IsNullOrEmpty(Dictionary)&&!File.Exists(Dictionary)&&!System.IO.Directory.Exists(Dictionary))throw new ArgumentException("补充名称词典不存在");
        if(!string.IsNullOrEmpty(BorrowedDictionary)&&!File.Exists(BorrowedDictionary)&&!System.IO.Directory.Exists(BorrowedDictionary))throw new ArgumentException("跨作品候选词典不存在");
        if(CrossAsset && (AssetType is "auto" or "xanim" or "sndasset" or "soundbank" or "soundbanktransient" or "soundbankalias" or "image" or "material") && !string.IsNullOrEmpty(RelatedFolder))
        {
            if(!System.IO.Directory.Exists(RelatedFolder))throw new ArgumentException("其他已命名资产文件夹不存在");
            if(IsWithin(Output,RelatedFolder))throw new ArgumentException("输出目录请选择其他已命名资产文件夹以外的位置");
        }
        return this;
    }
    private static bool IsWithin(string target,string root)
    {
        var relative=Path.GetRelativePath(Path.GetFullPath(root),Path.GetFullPath(target));
        return relative=="."||(!Path.IsPathRooted(relative)&&relative!=".."&&!relative.StartsWith(".."+Path.DirectorySeparatorChar,StringComparison.Ordinal));
    }
}

public sealed class CaptureReport
{
    [JsonPropertyName("status")] public string Status {get;set;}="";
    [JsonPropertyName("snapshot_file")] public string SnapshotFile {get;set;}="";
    [JsonPropertyName("records")] public long Records {get;set;}
    [JsonPropertyName("strings")] public long Strings {get;set;}
    [JsonPropertyName("complete")] public bool Complete {get;set;}
    [JsonPropertyName("message")] public string Message {get;set;}="";
    [JsonPropertyName("pid")] public int? ProcessId {get;set;}
    [JsonPropertyName("game")] public string Game {get;set;}="";
    [JsonExtensionData] public Dictionary<string,JsonElement>? Additional {get;set;}
}

public sealed class CaptureWorkerEvent
{
    [JsonPropertyName("event")] public string Event {get;set;}="";
    [JsonPropertyName("processed")] public long Processed {get;set;}
    [JsonPropertyName("message")] public string Message {get;set;}="";
    [JsonPropertyName("result")] public CaptureReport? Result {get;set;}
    [JsonExtensionData] public Dictionary<string,JsonElement>? Additional {get;set;}
}

public sealed class EstimateReport
{
    [JsonPropertyName("status")] public string Status {get;set;}="";
    [JsonPropertyName("target_count")] public long TargetCount {get;set;}
    [JsonPropertyName("candidate_total")] public long CandidateTotal {get;set;}
    [JsonPropertyName("budgeted_candidates")] public long BudgetedCandidates {get;set;}
    [JsonPropertyName("cached_candidates_lower_bound")] public long CachedCandidates {get;set;}
    [JsonPropertyName("collision_expectation")] public double CollisionExpectation {get;set;}
    [JsonPropertyName("estimated_seconds_range")] public double[] SecondsRange {get;set;}=[];
    [JsonPropertyName("coverage")] public JsonElement Coverage {get;set;}
    [JsonExtensionData] public Dictionary<string,JsonElement>? Additional {get;set;}
}

public sealed class RunReport
{
    [JsonPropertyName("version")] public string Version {get;set;}=AppVersion.Version;
    [JsonPropertyName("status")] public string Status {get;set;}="";
    [JsonPropertyName("entries")] public int Entries {get;set;}
    [JsonPropertyName("verified_target_matches")] public int VerifiedTargetMatches {get;set;}
    [JsonPropertyName("excluded_existing")] public int ExcludedExisting {get;set;}
    [JsonPropertyName("processed")] public long Processed {get;set;}
    [JsonPropertyName("path")] public string Path {get;set;}="";
    [JsonPropertyName("run_dir")] public string RunDir {get;set;}="";
    [JsonPropertyName("new_names_csv")] public string NewNamesCsv {get;set;}="";
    [JsonPropertyName("saluki_ready")] public string? SalukiReady {get;set;}
    // Preserve input/stages/cross_asset/future evidence fields without reflection.
    [JsonExtensionData] public Dictionary<string,JsonElement>? Additional {get;set;}
}

public sealed class WorkerEvent
{
    [JsonPropertyName("event")] public string Event {get;set;}="";
    [JsonPropertyName("processed")] public long Processed {get;set;}
    [JsonPropertyName("message")] public string Message {get;set;}="";
    [JsonPropertyName("result")] public RunReport? Result {get;set;}
    [JsonPropertyName("input_folder")] public string? InputFolder {get;set;}
    [JsonPropertyName("type")] public string? Type {get;set;}
    [JsonExtensionData] public Dictionary<string,JsonElement>? Additional {get;set;}
}

[JsonSourceGenerationOptions(WriteIndented=true,GenerationMode=JsonSourceGenerationMode.Metadata)]
[JsonSerializable(typeof(Config))]
[JsonSerializable(typeof(CaptureReport))]
[JsonSerializable(typeof(CaptureWorkerEvent))]
[JsonSerializable(typeof(RunReport))]
[JsonSerializable(typeof(WorkerEvent))]
[JsonSerializable(typeof(EstimateReport))]
[JsonSerializable(typeof(Dictionary<string,JsonElement>))]
public partial class FinderJsonContext : JsonSerializerContext { }
