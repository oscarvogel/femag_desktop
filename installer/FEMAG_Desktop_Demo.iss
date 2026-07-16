#define MyAppName "FEMAG Desktop DEMO"
#define MyAppVersion "2026.07.15-demo"
#define MyAppPublisher "Vogel Consultoria"
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
OutputBaseFilename=FEMAG_Desktop_DEMO_Standalone_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName=FEMAG Desktop DEMO
Uninstallable=yes
ArchitecturesAllowed=x64compatible
SetupIconFile=..\app\ui\assets\branding\femag.ico
UninstallDisplayIcon={app}\FEMAG Desktop DEMO.exe

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\FEMAG Desktop DEMO\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FEMAG Desktop DEMO"; Filename: "{app}\FEMAG Desktop DEMO.exe"; WorkingDir: "{app}"; IconFilename: "{app}\FEMAG Desktop DEMO.exe"
Name: "{autodesktop}\FEMAG Desktop DEMO"; Filename: "{app}\FEMAG Desktop DEMO.exe"; WorkingDir: "{app}"; IconFilename: "{app}\FEMAG Desktop DEMO.exe"; Tasks: desktopicon
Name: "{autoprograms}\Desinstalar FEMAG Desktop DEMO"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo de FEMAG Desktop DEMO en el escritorio"; GroupDescription: "Accesos directos:"; Flags: checkedonce

[Run]
Filename: "{app}\FEMAG Desktop DEMO.exe"; Description: "Abrir FEMAG Desktop DEMO"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\outputs"
Type: filesandordirs; Name: "{app}\backups"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if WizardSilent then
    Log('Instalacion silenciosa de FEMAG Desktop DEMO. La UI no se abrira automaticamente.');
  Result := '';
end;
