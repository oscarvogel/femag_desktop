; Instalador del agente de sincronizacion de FEMAG (#804).
;
; Requiere que la webapp del servidor ya tenga su webapp.env con los datos de
; MySQL. El sync.env (URL + token) se copia desde el archivo que prepara el
; responsable:
;   FEMAG_Sync_Agent_Setup.exe /SYNCENV=C:\ruta\femag_sync.env
; Si no se pasa /SYNCENV, se espera C:\ProgramData\FEMAG\sync.env.

#define MyAppName "FEMAG Sync Agent"
#define MyAppPublisher "Vogel Consultoria"
#ifndef MyAppVersion
  #define MyAppVersion "0000.00.00.00.00.00"
#endif

[Setup]
AppId={{DE6BFB36-7EBD-422E-9A43-DE1ACDC04675}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\FEMAG\sync
DefaultGroupName=FEMAG Sync Agent
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=FEMAG_Sync_Agent_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName={#MyAppName}
Uninstallable=yes
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
DisableDirPage=no
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\FEMAG Sync Agent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\instalar_sync_agent.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Desinstalar FEMAG Sync Agent"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\instalar_sync_agent.ps1"" -InstallRoot ""{app}"" -ConfigPath ""{commonappdata}\FEMAG\sync.env"" -WebappEnvPath ""{commonappdata}\FEMAG\webapp.env"""; StatusMsg: "Instalando y programando FEMAG Sync Agent..."; Flags: waituntilterminated

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName 'FEMAG Sync Agent' -Confirm:`$false -ErrorAction SilentlyContinue"""; Flags: runhidden waituntilterminated; RunOnceId: "FEMAGSyncAgentCleanup"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  SyncEnvParam: String;
  Target: String;
begin
  Target := ExpandConstant('{commonappdata}\FEMAG\sync.env');
  SyncEnvParam := ExpandConstant('{param:SYNCENV|}');

  if SyncEnvParam <> '' then
  begin
    if not FileExists(SyncEnvParam) then
    begin
      Result := 'No existe el archivo indicado en /SYNCENV: ' + SyncEnvParam;
      exit;
    end;
    ForceDirectories(ExtractFileDir(Target));
    if not CopyFile(SyncEnvParam, Target, False) then
    begin
      Result := 'No se pudo copiar ' + SyncEnvParam + ' a ' + Target;
      exit;
    end;
  end;

  if not FileExists(Target) then
  begin
    Result := 'Falta ' + Target + '. Copie alli el sync.env generado o ejecute el instalador con /SYNCENV=C:\ruta\femag_sync.env';
    exit;
  end;
  if not FileExists(ExpandConstant('{commonappdata}\FEMAG\webapp.env')) then
  begin
    Result := 'Falta C:\ProgramData\FEMAG\webapp.env. Instale primero el servidor de la webapp.';
    exit;
  end;

  Result := '';
end;
