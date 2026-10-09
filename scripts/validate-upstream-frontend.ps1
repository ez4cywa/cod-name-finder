#Requires -Version 7.0
param([string]$App="",[switch]$Publish)
# All contribution responses come from a local fixture. No network, credentials, fork or PR is created.
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$validation=Join-Path $taskRoot 'validation'
New-Item -ItemType Directory -Force -Path $validation | Out-Null
if([string]::IsNullOrEmpty($App)){$App=Join-Path $validation 'upstream-aot-app\CODNameFinder.exe'}
$App=[IO.Path]::GetFullPath($App)
function Check-Exit([string]$Operation){if($LASTEXITCODE-ne 0){throw "$Operation failed: $LASTEXITCODE"}}
foreach($name in @('upstream-bridge-stub','upstream-bridge-harness'))
{
    & dotnet build (Join-Path $taskRoot "tests\$name\$name.csproj") -c Release
    Check-Exit "Build $name"
}
if($Publish)
{
    & dotnet publish (Join-Path $taskRoot 'dotnet\CODNameFinder.App\CODNameFinder.App.csproj') -r win-x64 -c Release -p:RestoreLockedMode=true -o ([IO.Path]::GetDirectoryName($App))
    Check-Exit 'Publish NativeAOT frontend'
}
if(-not(Test-Path -LiteralPath $App -PathType Leaf)){throw 'Frontend missing; rerun with -Publish or supply -App'}
$previousEngine=$env:COD_NAME_FINDER_ENGINE
try
{
    $env:COD_NAME_FINDER_ENGINE=Join-Path $taskRoot 'tests\upstream-bridge-stub\bin\Release\net10.0\win-x64\upstream-bridge-stub.exe'
    $harness=Join-Path $taskRoot 'tests\upstream-bridge-harness\bin\Release\net10.0\win-x64\upstream-bridge-harness.exe'
    $coreLines=& $harness (Join-Path $validation 'upstream-bridge-fixtures')
    Check-Exit 'Core upstream bridge'
    $core=$coreLines | ConvertFrom-Json
    if(-not$core.passed-or -not$core.protocol_stub-or$core.real_network-or$core.checks-lt 30){throw 'Core contribution checks failed'}
    $coreLines | Set-Content -LiteralPath (Join-Path $validation 'upstream-bridge-validation.json') -Encoding utf8
    $self=(& $App selftest) | ConvertFrom-Json
    Check-Exit 'NativeAOT selftest'
    if(-not$self.native_aot-or$self.checks-ne 15){throw 'Expected NativeAOT typed frontend'}
    $fakeToken='ghp_FAKE_OFFLINE_VALIDATION_123'
    $fakeCredentials=@{token=$fakeToken;remember_token=$false} | ConvertTo-Json -Compress
    $cliLines=@($fakeCredentials | & $App upstream prepare --export (Join-Path $validation 'upstream-cli-中文') --stdin)
    Check-Exit 'NativeAOT upstream CLI forwarding'
    if(($cliLines -join "`n").Contains($fakeToken)){throw 'Fake secret appeared in protocol output'}
    $cli=$cliLines[-1] | ConvertFrom-Json
    if($cli.status-ne 'ready'-or$cli.eligible_count-ne 2-or -not$cli.submit_allowed){throw 'NativeAOT contribution result mismatch'}
    $screenshots=@()
    foreach($minimum in @($false,$true))
    {
        $name=if($minimum){'upstream-controls-minimum'}else{'upstream-controls'}
        $screenshot=Join-Path $validation ($name+'.png')
        $arguments=@('screenshot',$screenshot,'--validation','--upstream')
        if($minimum){$arguments+='--minimum'}
        $null=& $App @arguments
        Check-Exit "GUI $name"
        $state=Get-Content -LiteralPath ($screenshot+'.json') -Raw | ConvertFrom-Json
        $ui=$state.upstream_contribution
        if(-not$state.interactive_controls_centered-or$state.control_alignment_issues.Count-ne 0-or -not$state.actions_visible){throw 'Controls must be centered and actions visible'}
        if(-not$ui.controls-or -not$ui.token_masked-or$ui.automatic_enabled-or$ui.remember_credential-or -not$ui.session_only-or$ui.preview_enabled-or$ui.submit_enabled-or$ui.open_enabled){throw 'Contribution controls or session defaults mismatch'}
        $screenshots+=$screenshot
    }
    [ordered]@{passed=$true;protocol_stub=$true;real_network=$false;native_aot=$true;core_checks=$core.checks;stdin_credentials=$true;secret_redaction=$true;cli_forwarding=$true;interactive_controls_centered=$true;automatic_default_off=$true;token_masked=$true;session_only=$true;screenshots=$screenshots} | ConvertTo-Json -Depth 3 |
        Set-Content -LiteralPath (Join-Path $validation 'upstream-frontend-validation.json') -Encoding utf8
}finally{$env:COD_NAME_FINDER_ENGINE=$previousEngine}
