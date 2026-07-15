#define MyAppName "FEMAG Desktop DEMO"
#define MyAppVersion "2026.07.15-demo"
#define MyAppPublisher "Vogel Consultoria"
#ifndef SourceBranch
  #define SourceBranch "main"
#endif

[Setup]
AppId={{F4E7A5EE-3E2E-4A5D-8A28-DA9E741EDE01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\FEMAG Desktop DEMO
DefaultGroupName=FEMAG Desktop DEMO
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=FEMAG_Desktop_DEMO_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName=FEMAG Desktop DEMO
Uninstallable=yes
ArchitecturesAllowed=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\scripts\instalar_femag_demo.ps1"; DestDir: "{app}\bootstrap"; Flags: ignoreversion
Source: "abrir_femag_demo.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\FEMAG Desktop DEMO"; Filename: "{app}\abrir_femag_demo.cmd"; WorkingDir: "{app}"
Name: "{autodesktop}\FEMAG Desktop DEMO"; Filename: "{app}\abrir_femag_demo.cmd"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autoprograms}\Desinstalar FEMAG Desktop DEMO"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo de FEMAG Desktop DEMO en el escritorio"; GroupDescription: "Accesos directos:"; Flags: checkedonce

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\bootstrap\instalar_femag_demo.ps1"" -Branch ""{#SourceBranch}"" -InstallDir ""{app}\app"" -SkipUi"; StatusMsg: "Preparando FEMAG Desktop DEMO y sus datos SQLite..."; Flags: waituntilterminated
Filename: "{app}\abrir_femag_demo.cmd"; Description: "Abrir FEMAG Desktop DEMO"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\bootstrap"
Type: files; Name: "{app}\abrir_femag_demo.cmd"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if WizardSilent then
    Log('Instalacion silenciosa de FEMAG Desktop DEMO. La UI no se abrira automaticamente.');
  Result := '';
end;
