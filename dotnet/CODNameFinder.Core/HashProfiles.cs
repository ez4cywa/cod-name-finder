namespace CODNameFinder.Core;

// UI metadata only; the packaged engine owns all hashing and validation.
public sealed record HashProfile(string Id);
public static class HashProfiles
{
    public static readonly IReadOnlyDictionary<string,HashProfile> All = GeneratedRegistry.ProfileIds
        .ToDictionary(id=>id,id=>new HashProfile(id),StringComparer.Ordinal);
}
