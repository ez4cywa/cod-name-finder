#ifndef AppVersion
  #define AppVersion "2.2.2"
#endif
#ifndef SourceRoot
  #error SourceRoot must point to the built application directory
#endif
#ifndef OutputRoot
  #error OutputRoot must point to the release directory
#endif

[Setup]
AppId={code:GetApplicationId}
AppName=COD Name Finder
AppVersion={#AppVersion}
AppPublisher=COD Name Finder
DefaultDirName={localappdata}\Programs\CODNameFinder
DefaultGroupName=COD Name Finder
PrivilegesRequired=lowest
UsePreviousLanguage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir={#OutputRoot}
OutputBaseFilename=CODNameFinder-{#AppVersion}-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
LicenseFile={#SourceRoot}\LICENSE
UninstallDisplayIcon={app}\CODNameFinder.exe
CloseApplications=no
DisableProgramGroupPage=yes
SetupLogging=yes
SetupIconFile={#SourceRoot}\assets\cod-name-finder.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\COD Name Finder"; Filename: "{app}\CODNameFinder.exe"; WorkingDir: "{app}"; Flags: runminimized
Name: "{group}\Usage Tutorial"; Filename: "{app}\CODNameFinder.exe"; Parameters: "tutorial"; WorkingDir: "{app}"; Flags: runminimized
Name: "{autodesktop}\COD Name Finder"; Filename: "{app}\CODNameFinder.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Flags: runminimized

[Run]
Filename: "{app}\CODNameFinder.exe"; Description: "Launch COD Name Finder"; Flags: nowait postinstall skipifsilent runminimized

[Code]
function GetApplicationId(Param: String): String;
var I: Integer;
begin
  Result := 'CODNameFinder.575c3f51-8c17-4ffd-bb25-a1bcd51e5ec7';
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/VALIDATION') = 0 then
      Result := 'CODNameFinder.Validation.06d339f7-652f-45a5-9142-47c09b88f319';
end;
