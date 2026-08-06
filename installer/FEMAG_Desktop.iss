#define MyAppName "FEMAG Desktop"
#define MyAppPublisher "Vogel Consultoria"
#ifndef MyAppVersion
  #define MyAppVersion "0000.00.00.00.00.00"
#endif
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "FEMAG_Desktop_Produccion_Setup"
#endif

[Setup]
AppId={{10F03F3B-BA11-4F61-88DA-14DD2AA30EF4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\FEMAG Desktop
DefaultGroupName=FEMAG Desktop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName=FEMAG Desktop
Uninstallable=yes
ArchitecturesAllowed=x64compatible
SetupIconFile=..\app\ui\assets\branding\femag.ico
UninstallDisplayIcon={app}\FEMAG Desktop.exe

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\FEMAG Desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FEMAG Desktop"; Filename: "{app}\FEMAG Desktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\FEMAG Desktop.exe"
Name: "{autodesktop}\FEMAG Desktop"; Filename: "{app}\FEMAG Desktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\FEMAG Desktop.exe"; Tasks: desktopicon
Name: "{autoprograms}\Configurar conexion FEMAG"; Filename: "{app}\FEMAG Desktop.exe"; Parameters: "--configure"; WorkingDir: "{app}"
Name: "{autoprograms}\Desinstalar FEMAG Desktop"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo de FEMAG Desktop en el escritorio"; GroupDescription: "Accesos directos:"; Flags: checkedonce

[Run]
Filename: "{app}\FEMAG Desktop.exe"; Description: "Configurar y abrir FEMAG Desktop"; Flags: postinstall nowait skipifsilent unchecked

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if WizardSilent then
    Log('Instalacion silenciosa de FEMAG Desktop. La conexion se configurara en el primer inicio.');
  Result := '';
end;
