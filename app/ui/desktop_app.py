        return [(row.email, row.label or "", row.is_primary) for row in contacts]
    legacy = (getattr(client, "email", None) or "").strip()
    return [(legacy, "", True)] if legacy else []


def run_desktop_app(*, demo_mode: bool = False) -> int:
    app = QApplication.instance() or QApplication([])
    app.setWindowIcon(femag_icon())
    # El login conserva su diseño propio (incluida la imagen institucional).
    # El tema V2 global se aplica recién después de autenticar.
    try:
        database = _prepare_database(demo_mode=demo_mode)
    except RuntimeError as exc:
        QMessageBox.critical(None, "FEMAG Desktop - Base de datos", str(exc))
        return 1

    PermissionService().seed_defaults()
    _ensure_demo_user(demo_mode=demo_mode)
    if demo_mode:
        _seed_demo_masters()
    while True:
        app.setStyleSheet("")
        login = LoginWindow(demo_mode=demo_mode)
        if login.show() != QDialog.Accepted:
            return 0
        user = login.authenticated_user
        app.setStyleSheet(STYLES + glass_v2_stylesheet())
        window = FemagDesktopWindow(user=user, demo_mode=demo_mode or database is None)
        window.show()
        result = app.exec_()
        if not window.session_closed:
            break
    if database is not None and not database.is_closed():
        database.close()
    return result
