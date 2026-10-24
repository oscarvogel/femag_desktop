; Instalador del servidor de la webapp de FEMAG.
;
; Es el camino de instalacion en la fabrica: se corre este .exe, se escriben
; los datos de MySQL en el asistente y queda el servidor levantado, con
; arranque automatico y el firewall abierto.
;
; Modo simple (http, sin Caddy ni certificados): el flujo que pidio Oscar
; (cargar partes de embolsado desde el celular) no usa la camara, asi que no
; hace falta instalar nada en los telefonos.

#define MyAppName "FEMAG Webapp Server"
#define MyAppPublisher "Vogel Consultoria"
#ifndef MyAppVersion
  #define MyAppVersion "0000.00.00.00.00.00"
#endif

[Setup]
AppId={{3803817A-0DE7-46CD-81FA-2E72FCFFA676}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\FEMAG\webapp
DefaultGroupName=FEMAG Webapp Server
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=FEMAG_Webapp_Server_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName={#MyAppName}
Uninstallable=yes
ArchitecturesAllowed=x64compatible
; El instalador registra una tarea programada que corre como SYSTEM y abre el
; firewall: necesita privilegios de administrador.
PrivilegesRequired=admin
DisableDirPage=no
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\FEMAG Webapp Server\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\instalar_webapp_servidor.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Desinstalar FEMAG Webapp Server"; Filename: "{uninstallexe}"

[Run]
; Los datos van en un archivo temporal, no en la linea de comandos: la clave de
; MySQL queda expuesta en la lista de procesos mientras corre el instalador.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\instalar_webapp_servidor.ps1"" -InstallRoot ""{app}"" -ParamsFile ""{tmp}\femag-webapp-params.txt"""; StatusMsg: "Instalando el servidor de la webapp..."; Flags: waituntilterminated

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Stop-ScheduledTask -TaskName 'FEMAG Webapp QR' -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName 'FEMAG Webapp QR' -Confirm:`$false -ErrorAction SilentlyContinue; Get-NetFirewallRule -DisplayName 'FEMAG Webapp Server' -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue"""; Flags: runhidden waituntilterminated; RunOnceId: "FEMAGWebappServerCleanup"

[Code]
var
  ServerPage: TInputQueryWizardPage;
  DbPage: TInputQueryWizardPage;
  ParamsFile: String;
  DbPortValue: String;

{ Los parametros de linea de comandos permiten instalar sin asistente
  (instalacion desatendida):
    /HOST=femag.lan /WEBPORT=8000 /DBHOST=127.0.0.1 /DBPORT=3306
    /DBNAME=femag_desktop /DBUSER=femag_webapp /DBPASSWORD=...
  Los nombres no distinguen mayusculas. Lo que no se pasa toma el valor por
  defecto de la pagina. }
function ParamOrDefault(const Name: String; const DefaultValue: String): String;
begin
  Result := ExpandConstant('{param:' + Name + '|' + DefaultValue + '}');
end;

procedure InitializeWizard();
var
  HostParam: String;
  PortParam: String;
  DbHostParam: String;
  DbNameParam: String;
  DbUserParam: String;
  DbPasswordParam: String;
begin
  HostParam := ParamOrDefault('HOST', 'femag.lan');
  PortParam := ParamOrDefault('WEBPORT', '8000');
  DbHostParam := ParamOrDefault('DBHOST', '127.0.0.1');
  DbPortValue := ParamOrDefault('DBPORT', '3306');
  DbNameParam := ParamOrDefault('DBNAME', 'femag_desktop');
  DbUserParam := ParamOrDefault('DBUSER', '');
  DbPasswordParam := ParamOrDefault('DBPASSWORD', '');

  { Pagina del servidor }
  ServerPage := CreateInputQueryPage(wpSelectDir,
    'Datos del servidor',
    'El nombre es como lo resuelve el DNS de la planta.',
    'No debe terminar en .local: la RFC 6762 reserva ese sufijo para mDNS y los ' +
    'celulares no consultan el DNS de la LAN para esos nombres.');
  ServerPage.Add('Nombre del host (por ejemplo femag.lan):', False);
  ServerPage.Add('Puerto del servidor web (8000):', False);
  ServerPage.Values[0] := HostParam;
  ServerPage.Values[1] := PortParam;

  { Pagina de la base de datos }
  DbPage := CreateInputQueryPage(wpSelectDir,
    'Base de datos MySQL',
    'El servidor lee la base con este usuario.',
    'Necesita permiso de lectura y escritura, pero NO de crear ni alterar tablas: ' +
    'el esquema lo aplica un administrador desde FEMAG Desktop.');
  DbPage.Add('Servidor MySQL (127.0.0.1 si esta en la misma maquina):', False);
  DbPage.Add('Nombre de la base:', False);
  DbPage.Add('Usuario de MySQL:', False);
  DbPage.Add('Clave de MySQL:', True);
  DbPage.Values[0] := DbHostParam;
  DbPage.Values[1] := DbNameParam;
  DbPage.Values[2] := DbUserParam;
  DbPage.Values[3] := DbPasswordParam;
end;

{ El paso [Run] se ejecuta DESPUES de ssPostInstall: el archivo de parametros
  tiene que estar escrito antes, y el hook para eso es PrepareToInstall.
  Con ssPostInstall el instalador corria el script sin archivo y la
  instalacion fallaba en la fabrica. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Lines: TArrayOfString;
begin
  Result := '';
  NeedsRestart := False;

  if Trim(ServerPage.Values[0]) = '' then
  begin
    Result := 'Escribi el nombre del host.';
    exit;
  end;
  if Trim(ServerPage.Values[1]) = '' then
  begin
    Result := 'Escribi el puerto del servidor web.';
    exit;
  end;
  if Trim(DbPage.Values[1]) = '' then
  begin
    Result := 'Escribi el nombre de la base de datos.';
    exit;
  end;
  if Trim(DbPage.Values[2]) = '' then
  begin
    Result := 'Escribi el usuario de MySQL.';
    exit;
  end;

  { Los datos van en un archivo y no en la linea de comandos: la clave de
    MySQL queda expuesta en la lista de procesos mientras corre el
    instalador. UTF-8 con BOM para que PowerShell 5.1 lo lea bien. }
  ParamsFile := ExpandConstant('{tmp}\femag-webapp-params.txt');
  SetArrayLength(Lines, 8);
  Lines[0] := '# Datos del servidor webapp de FEMAG (clave de MySQL)';
  Lines[1] := 'PublicHostName=' + Trim(ServerPage.Values[0]);
  Lines[2] := 'WebPort=' + Trim(ServerPage.Values[1]);
  Lines[3] := 'DbHost=' + Trim(DbPage.Values[0]);
  Lines[4] := 'DbPort=' + Trim(DbPortValue);
  Lines[5] := 'DbName=' + Trim(DbPage.Values[1]);
  Lines[6] := 'DbUser=' + Trim(DbPage.Values[2]);
  Lines[7] := 'DbPassword=' + DbPage.Values[3];
  if not SaveStringsToUTF8File(ParamsFile, Lines, False) then
  begin
    Result := 'No se pudo escribir el archivo de datos en ' + ParamsFile + '.';
    exit;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WizardForm.StatusLabel.Caption := 'Instalando el servidor de la webapp...';
  if CurStep = ssDone then
  begin
    { El archivo tiene la clave de MySQL: no puede quedar en disco. }
    if ParamsFile <> '' then
      DeleteFile(ParamsFile);
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ServerPage.ID then
  begin
    if Trim(ServerPage.Values[0]) = '' then
    begin
      MsgBox('Escribi el nombre del host.', mbError, MB_OK);
      Result := False;
    end;
    if Trim(ServerPage.Values[1]) = '' then
    begin
      MsgBox('Escribi el puerto del servidor web.', mbError, MB_OK);
      Result := False;
    end;
  end;
  if CurPageID = DbPage.ID then
  begin
    if Trim(DbPage.Values[1]) = '' then
    begin
      MsgBox('Escribi el nombre de la base de datos.', mbError, MB_OK);
      Result := False;
    end;
    if Trim(DbPage.Values[2]) = '' then
    begin
      MsgBox('Escribi el usuario de MySQL.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
