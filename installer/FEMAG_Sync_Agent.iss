; Instalador del agente de sincronizacion de FEMAG (#804).
;
; Requiere la webapp del servidor con su webapp.env. El femag_sync.env
; (URL + token) se copia junto al instalador o se pasa con:
;   FEMAG_Sync_Agent_Setup.exe /SYNCENV=C:\ruta\femag_sync.env
;
; El instalador pide una vez un usuario MySQL administrador para crear las
; tablas de sync si el usuario de la webapp no tiene permiso DDL.

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
Source: "sync_schema.sql"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Desinstalar FEMAG Sync Agent"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\instalar_sync_agent.ps1"" -InstallRoot ""{app}"" -ConfigPath ""{commonappdata}\FEMAG\sync.env"" -WebappEnvPath ""{commonappdata}\FEMAG\webapp.env"" -ParamsFile ""{tmp}\femag-sync-params.txt"" -RunSync"; StatusMsg: "Instalando, creando tablas y sincronizando..."; Flags: waituntilterminated

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName 'FEMAG Sync Agent' -Confirm:`$false -ErrorAction SilentlyContinue"""; Flags: runhidden waituntilterminated; RunOnceId: "FEMAGSyncAgentCleanup"

[Code]
var
  DbAdminPage: TInputQueryWizardPage;
  ParamsFile: String;

procedure InitializeWizard();
begin
  DbAdminPage := CreateInputQueryPage(
    wpSelectDir,
    'MySQL administrador',
    'Solo se usa una vez para crear las tablas de sincronizacion.',
    'El usuario de la webapp puede no tener permiso para crear tablas. ' +
    'Esta clave no se guarda en ningun archivo permanente.');
  DbAdminPage.Add('Usuario MySQL administrador:', False);
  DbAdminPage.Add('Clave:', True);
  DbAdminPage.Values[0] := 'root';
  DbAdminPage.Values[1] := '';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  SyncEnvParam: String;
  SourceEnv: String;
  Target: String;
  Lines: TArrayOfString;
begin
  Result := '';
  NeedsRestart := False;
  Target := ExpandConstant('{commonappdata}\FEMAG\sync.env');
  SyncEnvParam := ExpandConstant('{param:SYNCENV|}');

  if SyncEnvParam <> '' then
    SourceEnv := SyncEnvParam
  else if FileExists(ExpandConstant('{src}\femag_sync.env')) then
    SourceEnv := ExpandConstant('{src}\femag_sync.env')
  else
    SourceEnv := '';

  if SourceEnv <> '' then
  begin
    if not FileExists(SourceEnv) then
    begin
      Result := 'No existe el archivo de configuracion: ' + SourceEnv;
      exit;
    end;
    ForceDirectories(ExtractFileDir(Target));
    if not CopyFile(SourceEnv, Target, False) then
    begin
      Result := 'No se pudo copiar ' + SourceEnv + ' a ' + Target;
      exit;
    end;
  end;

  if not FileExists(Target) then
  begin
    Result := 'Falta ' + Target + '. Copie femag_sync.env junto al instalador.';
    exit;
  end;
  if not FileExists(ExpandConstant('{commonappdata}\FEMAG\webapp.env')) then
  begin
    Result := 'Falta C:\ProgramData\FEMAG\webapp.env. Instale primero el servidor de la webapp.';
    exit;
  end;

  ParamsFile := ExpandConstant('{tmp}\femag-sync-params.txt');
  SetArrayLength(Lines, 3);
  Lines[0] := '# Datos para crear tablas de sync';
  Lines[1] := 'InitDbUser=' + Trim(DbAdminPage.Values[0]);
  Lines[2] := 'InitDbPassword=' + DbAdminPage.Values[1];
  if not SaveStringsToUTF8File(ParamsFile, Lines, False) then
  begin
    Result := 'No se pudo escribir el archivo temporal de instalacion.';
    exit;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
  begin
    if ParamsFile <> '' then
      DeleteFile(ParamsFile);
  end;
end;
