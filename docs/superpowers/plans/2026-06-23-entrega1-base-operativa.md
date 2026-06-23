# FEMAG Entrega 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the initial operational desktop base for FEMAG so users can configure security, load masters, audit changes, run backups, and validate the app with tests and smoke checks.

**Architecture:** Keep domain behavior in Peewee models and service classes, with UI modules limited to simple PySide-compatible windows and placeholders. Tests use an isolated SQLite database while runtime settings default to configurable MySQL via `.env`.

**Tech Stack:** Python 3, Peewee, PyMySQL, python-dotenv, PySide6-compatible UI, pytest, logging.

---

### Task 1: Base Project And Models

**Files:**
- Create: `app/config/settings.py`
- Create: `app/config/database.py`
- Create: `app/config/logging_config.py`
- Create: `app/models/base.py`
- Create: `app/models/security.py`
- Create: `app/models/audit.py`
- Create: `app/models/masters.py`
- Create: `app/models/system.py`
- Create: `scripts/init_db.py`
- Test: `tests/test_config.py`
- Test: `tests/test_models.py`

- [ ] Write failing tests for settings loading, database binding, model table creation, unique CUIT/domain constraints, and smoke imports.
- [ ] Run `python -m pytest tests/test_config.py tests/test_models.py -q` and confirm failures come from missing app modules.
- [ ] Implement settings, database proxy, base model, security/audit/masters/system models, and init script.
- [ ] Re-run targeted tests and confirm they pass.

### Task 2: Security, Permissions, And Audit

**Files:**
- Create: `app/services/auth_service.py`
- Create: `app/services/permission_service.py`
- Create: `app/services/audit_service.py`
- Test: `tests/test_permissions.py`
- Test: `tests/test_audit.py`

- [ ] Write failing tests for password hashing, login success/failure audit, default profile permissions, sensitive admin validation, and reprint behavior.
- [ ] Run targeted tests and confirm failures come from missing services.
- [ ] Implement auth, permission, and audit services.
- [ ] Re-run targeted tests and confirm they pass.

### Task 3: Dashboard And Menu

**Files:**
- Create: `app/ui/menu.py`
- Create: `app/ui/dashboard.py`
- Create: `app/ui/main_window.py`
- Create: `app/ui/login_window.py`
- Create: `app/main.py`
- Test: `tests/test_ui_smoke.py`

- [ ] Write failing tests for menu filtering, dashboard counters, future-module placeholders, and `python -m app.main --smoke`.
- [ ] Run targeted tests and confirm failures come from missing UI/main modules.
- [ ] Implement lightweight UI descriptors and optional PySide windows with headless smoke support.
- [ ] Re-run targeted tests and confirm they pass.

### Task 4: Masters Services

**Files:**
- Create: `app/services/client_service.py`
- Create: `app/services/master_service.py`
- Test: `tests/test_clients.py`
- Test: `tests/test_masters.py`

- [ ] Write failing tests for client/address creation, one fiscal address, one principal delivery address, operational masters, and audit entries.
- [ ] Run targeted tests and confirm failures come from missing services.
- [ ] Implement client and master services with audit calls.
- [ ] Re-run targeted tests and confirm they pass.

### Task 5: Backup, Docs, And Validation

**Files:**
- Create: `app/services/backup_service.py`
- Create: `scripts/run_backup.py`
- Create: `docs/guia_instalacion.md`
- Create: `docs/guia_usuario_entrega_1.md`
- Modify: `README.md`
- Test: `tests/test_backup.py`

- [ ] Write failing tests for manual backup command construction, backup log recording, configured destination folders, and audit entries.
- [ ] Run targeted tests and confirm failures come from missing backup service.
- [ ] Implement backup service and script.
- [ ] Add operational docs and update README commands.
- [ ] Run `python -m pytest`, `python -m compileall app`, and `python -m app.main --smoke`.
- [ ] Commit, push, and open PRs for the Entrega 1 blocks with summaries, validations, risks, and pending items.
