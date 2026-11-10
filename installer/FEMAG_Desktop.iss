#define MyAppName "FEMAG Desktop Produccion"
#define MyAppPublisher "Vogel Consultoria"
#ifndef MyAppVersion
  #define MyAppVersion "0000.00.00.00.00.00"
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
OutputBaseFilename=FEMAG_Desktop_Produccion_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName={#MyAppName}
Uninstallable=yes
ArchitecturesAllowed=x64compatible
SetupIconFile=..\app\ui\assets\branding\femag.ico
UninstallDisplayIcon={app}\FEMAG Desktop.exe
; Con la app abierta, el EXE no se reemplaza y el usuario sigue viendo la
; version vieja: hay que cerrar la aplicacion antes de instalar. Con esto,
; Inno Setup la cierra sola (tambien en instalacion silenciosa) y, si no
; puede, avisa en vez de dejar el puesto con un build viejo.
CloseApplications=yes
RestartApplications=yes

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
procedure CreateAiCaptureConfig();
var
  ConfigDir: String;
  ConfigPath: String;
  Content: String;
begin
  { La precarga con IA (#913) lee la API key desde el .env del runtime del
    puesto. Se crea solo la primera vez para no pisar la clave cargada. }
  ConfigDir := ExpandConstant('{localappdata}\FEMAG Desktop');
  ForceDirectories(ConfigDir);
  ConfigPath := AddBackslash(ConfigDir) + '.env';
  if FileExists(ConfigPath) then
    exit;
  Content :=
    '# Precarga con IA (#913). Pegar la API key de MiniMax y reiniciar FEMAG Desktop.' + #13#10 +
    'FEMAG_ORDER_CAPTURE_AI_PROVIDER=minimax' + #13#10 +
    'FEMAG_ORDER_CAPTURE_AI_API_KEY=' + #13#10;
  SaveStringToFile(ConfigPath, Content, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    CreateAiCaptureConfig();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if WizardSilent then
    Log('Instalacion silenciosa de FEMAG Desktop. La conexion se configurara en el primer inicio.');
  Result := '';
end;
