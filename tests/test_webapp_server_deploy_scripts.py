from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_webapp_server.ps1"
ENV_TEMPLATE = ROOT / "scripts" / "webapp-server.env.example"
WINDOWS_GUIDE = ROOT / "docs" / "WEBAPP_SERVER_WINDOWS.md"
WEB_REQUIREMENTS = ROOT / "requirements-web.txt"


def test_webapp_server_deployment_is_redeployable_and_keeps_mysql_local():
    content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert '"/MIR"' in content
    assert "FEMAG_AUTO_MIGRATE_SCHEMA=0" in content
    assert "127.0.0.1" in content
    assert "FEMAG Webapp QR" in content
    assert "Wait-ForHealthCheck" in content
    assert "*.credential" in content
    assert '".env"' in content


def test_webapp_server_configuration_template_has_no_real_credential():
    content = ENV_TEMPLATE.read_text(encoding="utf-8")

    assert "DB_PASSWORD=REEMPLAZAR_POR_CLAVE_SEGURA" in content
    assert "FEMAG_AUTO_MIGRATE_SCHEMA=0" in content
    assert "DB_HOST=127.0.0.1" in content


def test_webapp_server_public_name_does_not_use_the_mdns_local_suffix():
    """`.local` esta reservado para mDNS (RFC 6762).

    Los celulares resuelven los nombres `.local` por multicast y no consultan
    el DNS de la LAN, asi que el QR de turnos abriria en el telefono sin
    encontrar el servidor. La RFC recomienda `.lan` para redes privadas.
    """
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    template = ENV_TEMPLATE.read_text(encoding="utf-8")

    assert '$PublicHostName = "femag.lan"' in script
    assert "FEMAG_WEB_PUBLIC_URL=https://femag.lan" in template
    assert "femag.local" not in template


def test_windows_deployment_guide_covers_first_install_and_redeploy():
    content = WINDOWS_GUIDE.read_text(encoding="utf-8")

    assert "## Paso 3 — Primer despliegue" in content
    assert "## Re-despliegue" in content
    assert "Caddy" in content
    assert "/health" in content


def test_windows_deployment_guide_covers_the_factory_install_steps():
    """El runbook es lo que va a seguir el administrador en la fábrica.

    Si le falta un paso, la instalación se frena en la planta y no hay a quién
    consultar.
    """
    content = WINDOWS_GUIDE.read_text(encoding="utf-8")

    for section in (
        "## Paso 0 — Preparar la base",
        "## Paso 1 — Instalar Python y Caddy",
        "## Paso 3 — Primer despliegue",
        "## Paso 4 — DNS interno",
        "## Paso 5 — Perfil de red y firewall",
        "## Paso 6 — Distribuir la CA raíz de Caddy",
        "## Paso 7 — Validar",
        "## Re-despliegue",
        "## Rollback",
        "## Problemas frecuentes",
    ):
        assert section in content, section

    # La CA interna exige dos pasos en iOS: instalar el perfil y activar la
    # confianza completa. Con uno solo, Safari sigue avisando.
    assert "Certificate Trust Settings" in content
    assert "Install a certificate" in content

    # El certificado de la CA hay que sacarlo del perfil del servicio.
    assert "root.crt" in content
    assert "systemprofile" in content

    # El runbook tiene que ofrecer el modo sin HTTPS: es el que no le pide
    # nada al operario y es el que se va a usar para arrancar.
    assert "## Los dos modos" in content
    assert "-SkipCaddy" in content
    assert "cámara nativa" in content

    # El instalador de FEMAG Desktop es la app de escritorio (PyQt5) y NO
    # incluye el paquete webapp: hay que avisarlo antes de que alguien lo
    # instale en el servidor creyendo que con eso alcanza.
    assert "El instalador de FEMAG Desktop NO sirve para el servidor" in content
    assert "no incluye el paquete" in content

    # El checkout local pesa 1,4 GB de venvs y builds: hay que copiar solo lo
    # que la webapp carga, y la webapp no carga app.ui (no necesita PyQt).
    assert "1,4 GB" in content
    assert "app.ui" in content
    assert "/XD .git .venv" in content

    # El nombre publico no puede terminar en .local (RFC 6762 / mDNS).
    assert "femag.lan" in content
    assert "femag.local" not in content


def test_webapp_server_dependencies_do_not_pull_the_desktop_stack():
    """El servidor no necesita PyQt ni git.

    ``requirements.txt`` es la lista del escritorio: PyQt5 y ``pyqt5libs`` desde
    git. Si la webapp la arrastra, el Windows Server de la fabrica necesita Git
    instalado y salida a internet para descargar algo que la webapp nunca
    importa.
    """
    lines = [
        line.strip()
        for line in WEB_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert not any(line.startswith("-r") for line in lines), lines
    assert not any("PyQt5" in line for line in lines), lines
    assert not any("git+" in line for line in lines), lines

    # Lo que la webapp si usa: peewee, PyMySQL, dotenv, Pillow, reportlab,
    # Flask y waitress.
    for package in ("peewee", "PyMySQL", "python-dotenv", "Pillow", "reportlab", "Flask", "waitress"):
        assert any(line.startswith(package) for line in lines), (package, lines)


def test_webapp_server_publishes_the_https_url_that_the_turn_qr_uses():
    """El QR de cada turno tiene que salir con la URL que el celular puede abrir.

    Sin ``FEMAG_WEB_PUBLIC_URL`` el QR se arma con la direccion interna que ve
    el propio servidor, que desde el celular no sirve.
    """
    content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "FEMAG_WEB_PUBLIC_URL" in content
    assert "https://$PublicHostName" in content
    # Un http://pubblicado rompe la camara del celular: el despliegue lo frena.
    assert "debe empezar con https://" in content


def test_webapp_server_keeps_the_session_secret_out_of_the_system_profile():
    """El secreto de sesion no puede depender del perfil de SYSTEM.

    Va junto a la configuracion, con los mismos permisos restringidos.
    """
    content = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    template = ENV_TEMPLATE.read_text(encoding="utf-8")

    assert "FEMAG_WEB_SECRET_FILE" in content
    assert "webapp_secret.key" in content
    assert "FEMAG_WEB_SECRET_FILE=" in template


def test_webapp_server_covers_the_windows_network_profile_and_port_443():
    """En la fabrica el servidor puede quedar en perfil de red Public.

    Con la regla de firewall restringida a Domain/Private el celular no entra
    y parece un problema de HTTPS.
    """
    content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "FirewallProfiles" in content
    assert "Get-NetConnectionProfile" in content
    assert "Get-NetTCPConnection -LocalPort 443" in content


def test_webapp_server_script_is_utf8_with_bom_for_powershell_5_1():
    """Windows Server 2019 corre PowerShell 5.1.

    Un .ps1 sin BOM se lee como Windows-1252: los acentos se rompen y, si
    algun byte cae en el rango de las comillas tipograficas, el script deja de
    parsear y no arranca.
    """
    raw = DEPLOY_SCRIPT.read_bytes()

    assert raw.startswith(b"\xef\xbb\xbf"), (
        "deploy_webapp_server.ps1 necesita BOM UTF-8 para que PowerShell 5.1 lo lea bien."
    )


def test_webapp_server_can_run_without_https_and_without_caddy():
    """El flujo de partes no usa la cámara, así que no hace falta HTTPS.

    La pantalla de producción no llama a getUserMedia: el turno se elige de un
    select nativo. El QR de turno se escanea con la cámara NATIVA del celular,
    que no exige contexto seguro. Entonces se puede servir por http, sin Caddy
    y sin instalar un certificado en cada teléfono.
    """
    content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    # Sin Caddy la webapp tiene que escuchar en la placa, no en loopback.
    assert '$webHost = "0.0.0.0"' in content
    assert '$webHost = "127.0.0.1"' in content
    assert 'set "FEMAG_WEB_HOST=$webHost"' in content

    # El QR de turno tiene que llevar el puerto cuando no hay proxy inverso.
    assert "http://${PublicHostName}:$WebPort" in content

    # El firewall tiene que abrir el puerto del backend, no el 443.
    assert 'Set-WebappFirewallRule -Port $WebPort -DisplayName "FEMAG Webapp HTTP"' in content


def test_production_screen_does_not_need_the_camera():
    """La pantalla que pidió Oscar (cargar partes) no usa la cámara.

    Si esto cambia, el modo sin HTTPS deja de servir y hay que volver a
    pensar el certificado.
    """
    template = (ROOT / "webapp" / "templates" / "production.html").read_text(encoding="utf-8")

    assert "getUserMedia" not in template
    assert "mediaDevices" not in template
    # El turno se elige de un select nativo: son tres opciones.
    assert '<select id="turno"' in template


def test_webapp_session_cookie_does_not_require_https():
    """Sin HTTPS la cookie de sesión tiene que poder viajar en http.

    Flask no marca la cookie como secure salvo que se lo pidan, así que el
    login funciona por http: por eso el modo sin Caddy es viable.
    """
    offenders = [
        path.name
        for path in (ROOT / "webapp").glob("*.py")
        if "SESSION_COOKIE_SECURE" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        f"Si la cookie de sesion exige HTTPS, el modo sin Caddy deja de poder "
        f"iniciar sesion desde el celular: {offenders}"
    )
