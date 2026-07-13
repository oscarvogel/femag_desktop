# Share Account Statement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WhatsApp handoff and SMTP email delivery for the existing customer account-statement PDF.

**Architecture:** Keep transport concerns outside the UI. A focused sharing service will normalize Argentine/international phone numbers and build a `wa.me` URL; a focused mail service will load validated SMTP settings from the environment and attach an existing PDF. `FemagDesktopWindow` will coordinate PDF generation, confirmation/messages, browser opening, and mail sending, while `CustomerLedgerPage` only exposes callbacks for the selected client.

**Tech Stack:** Python 3.13, PyQt5, stdlib `email`/`smtplib`/`webbrowser`, pytest.

---

### Task 1: WhatsApp URL service

**Files:**
- Create: `app/services/account_statement_share_service.py`
- Create: `tests/test_account_statement_share_service.py`

- [ ] **Step 1: Write failing tests** covering international phone normalization, Argentine `0`/`15` cleanup, missing phone rejection, and URL encoding of the customer message.
- [ ] **Step 2: Run** `python -m pytest tests/test_account_statement_share_service.py -q` and confirm failure because the module does not exist.
- [ ] **Step 3: Implement** `normalize_whatsapp_phone(phone: str) -> str` and `build_whatsapp_url(client_name: str, phone: str) -> str` using `urllib.parse.urlencode`; reject empty or unusable numbers with a Spanish `ValueError`.
- [ ] **Step 4: Re-run** the focused tests and confirm they pass.

### Task 2: SMTP mail service

**Files:**
- Create: `app/services/account_statement_mail_service.py`
- Create: `tests/test_account_statement_mail_service.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing tests** for environment parsing, missing required settings, TLS selection, recipient validation, PDF attachment metadata, and SMTP login/send behavior through dependency injection.
- [ ] **Step 2: Run** `python -m pytest tests/test_account_statement_mail_service.py -q` and confirm failure because the module does not exist.
- [ ] **Step 3: Implement** immutable `SmtpSettings.from_env()`, `build_account_statement_message(...)`, and `send_account_statement(...)`; use `SMTP` with optional STARTTLS and never include passwords in exception messages.
- [ ] **Step 4: Add** documented `FEMAG_SMTP_HOST`, `FEMAG_SMTP_PORT`, `FEMAG_SMTP_USER`, `FEMAG_SMTP_PASSWORD`, `FEMAG_SMTP_FROM`, and `FEMAG_SMTP_USE_TLS` entries to `.env.example` with blank/non-secret values.
- [ ] **Step 5: Re-run** the focused tests and confirm they pass.

### Task 3: Customer-ledger actions

**Files:**
- Modify: `app/ui/customer_ledger.py`
- Modify: `app/ui/desktop_app.py`
- Modify: `tests/test_customer_ledger_ui.py`
- Create: `tests/test_account_statement_sharing_ui.py`

- [ ] **Step 1: Write failing UI tests** proving the two buttons exist, remain disabled without callbacks/selection, and dispatch the selected client to their callbacks.
- [ ] **Step 2: Write failing coordinator tests** proving missing contact data is reported, WhatsApp opens the generated URL after creating the PDF, email asks for confirmation, and SMTP errors are shown without escaping the handler.
- [ ] **Step 3: Run** the focused UI tests and confirm failures are caused by missing buttons/handlers.
- [ ] **Step 4: Add** `whatsapp_statement_callback` and `email_statement_callback` to `CustomerLedgerPage`, two explicit buttons, shared selected-client lookup, and enable/clear behavior consistent with the existing print action.
- [ ] **Step 5: Add** `_share_account_statement_whatsapp` and `_email_account_statement` coordinators to `FemagDesktopWindow`; reuse `export_account_statement`, open WhatsApp through `webbrowser`, confirm SMTP delivery with `QMessageBox`, and surface Spanish operational errors.
- [ ] **Step 6: Re-run** the focused UI tests and confirm they pass.

### Task 4: Verification and PR

**Files:**
- Modify only files already listed if verification reveals an issue.

- [ ] **Step 1: Run** `python -m pytest` and require zero failures.
- [ ] **Step 2: Run** `python -m compileall app` and require exit code 0.
- [ ] **Step 3: Run** `python -m app.main --smoke` and require exit code 0.
- [ ] **Step 4: Run** `git diff --check` and inspect `git status -sb` plus the complete diff.
- [ ] **Step 5: Commit** with `feat(cta-cte): compartir extracto por WhatsApp y correo`.
- [ ] **Step 6: Push** `codex/issue-176-share-statement` and open a draft PR linked with `Closes #176`, including validations, scope, risks, and the manual SMTP/WhatsApp verification status.
