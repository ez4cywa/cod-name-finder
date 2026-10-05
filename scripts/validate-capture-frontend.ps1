#Requires -Version 7.0
param(
    [string]$App = "",
    [switch]$Publish
)
# Protocol-only fixture; this never opens a game or Cordycep process.
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$validation = Join-Path $taskRoot 'validation'
$bridgeSupport = Join-Path $taskRoot 'tests'
if ([string]::IsNullOrEmpty($App)) { $App = Join-Path $validation 'capture-aot-app\CODNameFinder.exe' }
$App = [IO.Path]::GetFullPath($App)
function Check-Exit([string]$Operation) { if ($LASTEXITCODE -ne 0) { throw "$Operation failed: $LASTEXITCODE" } }
& dotnet build (Join-Path $bridgeSupport 'capture-bridge-stub\capture-bridge-stub.csproj') -c Release -p:RestoreLockedMode=true
Check-Exit 'Build protocol stub'
& dotnet build (Join-Path $bridgeSupport 'capture-bridge-harness\capture-bridge-harness.csproj') -c Release -p:RestoreLockedMode=true
Check-Exit 'Build Core protocol checks'
if ($Publish) {
    & dotnet publish (Join-Path $taskRoot 'dotnet\CODNameFinder.App\CODNameFinder.App.csproj') -r win-x64 -c Release -p:RestoreLockedMode=true -o ([IO.Path]::GetDirectoryName($App))
    Check-Exit 'Publish NativeAOT frontend'
}
if (-not (Test-Path -LiteralPath $App -PathType Leaf)) { throw "NativeAOT frontend missing: $App; rerun with -Publish" }
$oldEngine = $env:COD_NAME_FINDER_ENGINE
try {
    $env:COD_NAME_FINDER_ENGINE = Join-Path $bridgeSupport 'capture-bridge-stub\bin\Release\net10.0\win-x64\capture-bridge-stub.exe'
    $fixtures = Join-Path $validation 'capture-bridge-fixtures'
    $coreOutput = & (Join-Path $bridgeSupport 'capture-bridge-harness\bin\Release\net10.0\win-x64\capture-bridge-harness.exe') $fixtures
    Check-Exit 'Core capture bridge'
    $coreOutput | Set-Content -LiteralPath (Join-Path $validation 'capture-bridge-validation.json') -Encoding utf8
    $core = $coreOutput | ConvertFrom-Json
    if (-not $core.passed -or -not $core.protocol_stub) { throw 'Core checks did not pass' }
    $self = (& $App selftest) | ConvertFrom-Json
    Check-Exit 'NativeAOT selftest'
    if (-not $self.native_aot -or $self.checks -ne 15) { throw 'Frontend is not NativeAOT or typed JSON selftest failed' }
    $directory = Join-Path $fixtures 'Cordycep 中文目录'
    $cases = @(
        @{ Name='attached'; Game='COD2026'; Extra=@(); Complete=$true; Script='RunMW7Beta.bat' },
        @{ Name='launched'; Game='BO7'; Extra=@('--launch'); Complete=$true; Script='RunBO7.bat' },
        @{ Name='launched-custom'; Game='COD2026'; Extra=@('--launch','--script','自选 Beta 加载.bat'); Complete=$true; Script='自选 Beta 加载.bat' },
        @{ Name='cancelled'; Game='COD2026'; Extra=@('--stop-after','1'); Complete=$false; Script='RunMW7Beta.bat' }
    )
    $guiChecks = @()
    foreach ($case in $cases) {
        $output = Join-Path $validation ('capture-ui-' + $case.Name)
        $arguments = @('gui-capture',$directory,'--game',$case.Game,'--output',$output,'--validation') + $case.Extra
        $lines = @(& $App @arguments)
        Check-Exit ('GUI capture ' + $case.Name)
        $lines | Set-Content -LiteralPath (Join-Path $validation ('capture-ui-' + $case.Name + '.jsonl')) -Encoding utf8
        $events = @($lines | ForEach-Object { $_ | ConvertFrom-Json })
        $state = $events | Where-Object event -eq gui_validation | Select-Object -First 1
        $capture = ($events | Where-Object event -eq result | Select-Object -First 1).result
        if (-not $state.native_aot -or -not $state.actions_visible -or -not $state.input_mode_dropdown -or -not $state.snapshot_file_picker -or -not $state.cordycep_capture_controls) { throw 'Required GUI controls missing' }
        if (-not $state.bat_dropdown -or $state.bat_count -ne 4 -or $state.selected_script -ne $case.Script) { throw 'BAT dropdown selection mismatch' }
        if (-not $capture.protocol_stub -or $capture.complete -ne $case.Complete -or -not (Test-Path -LiteralPath $capture.snapshot_file -PathType Leaf)) { throw 'Capture completion/report mismatch' }
        if ($case.Complete) {
            if ($state.input_mode -ne 'snapshot' -or $state.snapshot_file -ne $capture.snapshot_file -or $state.estimate_available) { throw 'Complete capture must select snapshot and invalidate estimate' }
        } else {
            if ($state.input_mode -ne 'folder' -or $state.snapshot_file -ne '' -or -not $state.stopped_by_request) { throw 'Partial capture changed original input or missed stop' }
        }
        if ($case.Name.StartsWith('launched') -and (-not $capture.launch -or $capture.load_all -or $capture.script -ne $case.Script)) { throw 'GUI launch must pass selected --script without implicit --load-all' }
        if ($case.Name -eq 'attached' -and ($capture.launch -or $capture.load_all -or $capture.script -ne '')) { throw 'Attachment unexpectedly requested loading or a script' }
        $guiChecks += $case.Name
    }
    $statusLines = & $App cordycep status --directory $directory
    Check-Exit 'CLI Cordycep forwarding'
    $status = $statusLines | ConvertFrom-Json
    if ($status.directory -ne $directory) { throw 'CLI failed to forward absolute directory' }
    $cliControl = Join-Path $validation 'capture-script-cli-control.txt'
    'run' | Set-Content -LiteralPath $cliControl -Encoding ascii
    $cliScript = '自选 Beta 加载.bat'
    $scriptLines = & $App cordycep capture --directory $directory --game COD2026 --output (Join-Path $validation 'capture-script-cli') --control $cliControl --launch --script $cliScript
    Check-Exit 'CLI selected BAT forwarding'
    $scriptCapture = (($scriptLines | ForEach-Object { $_ | ConvertFrom-Json }) | Where-Object event -eq result | Select-Object -First 1).result
    if (-not $scriptCapture.launch -or $scriptCapture.script -ne $cliScript -or $scriptCapture.load_all) { throw 'CLI selected BAT was changed while forwarding' }
    [ordered]@{
        passed=$true; protocol_stub=$true; live_cordycep_test=$false;
        native_aot=$self.native_aot; typed_core_checks=$self.checks;
        gui_cases=$guiChecks; cancellation_keeps_original_input=$true;
        complete_capture_selects_snapshot=$true; cli_forwarding=$true;
        bat_dropdown=$true; bat_root_enumeration=$true; bat_game_defaults=$true;
        bat_user_selection_preserved=$true; unicode_script_forwarding=$true
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $validation 'capture-frontend-validation.json') -Encoding utf8
} finally { $env:COD_NAME_FINDER_ENGINE = $oldEngine }
