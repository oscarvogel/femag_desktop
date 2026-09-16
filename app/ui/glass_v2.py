from __future__ import annotations

from app.ui.branding import branding_asset_path


def glass_v2_stylesheet() -> str:
    background = branding_asset_path("femag-starch-v2.svg").as_posix()
    return f"""
    QWidget#femagV2Root {{
        background-color: #edf3f9;
        background-image: url("{background}");
        background-position: center;
        background-repeat: no-repeat;
    }}

    QFrame#femagV2Shell {{
        background-color: rgba(248, 251, 255, 224);
        border: 1px solid rgba(255,255,255,220);
        border-radius: 24px;
    }}

    QFrame#sidebarContainer {{
        background-color: rgba(237, 244, 252, 225);
        border: 1px solid rgba(255,255,255,215);
        border-radius: 20px;
    }}

    QLabel#sidebarBrandLogo {{
        background: transparent;
        border: none;
    }}

    QListWidget#sidebar {{
        background: transparent;
        border: none;
        outline: none;
        padding: 4px;
    }}

    QListWidget#sidebar::item {{
        min-height: 42px;
        margin: 3px 0;
        padding-left: 14px;
        border-radius: 11px;
        color: #385778;
    }}

    QListWidget#sidebar::item:hover {{
        background-color: rgba(255,255,255,150);
    }}

    QListWidget#sidebar::item:selected {{
        background-color: rgba(255,255,255,225);
        border: 1px solid rgba(108,153,211,120);
        color: #0b63c7;
        font-weight: 700;
    }}

    QFrame#topbar {{
        background: transparent;
        border: none;
        min-height: 64px;
    }}

    QLabel#topbarBrandLogo {{
        background: transparent;
        border: none;
    }}

    QLineEdit#globalSearch {{
        min-height: 42px;
        background-color: rgba(255,255,255,220);
        border: 1px solid rgba(194,210,229,210);
        border-radius: 12px;
        padding: 0 14px;
        color: #294b70;
    }}

    QLineEdit#globalSearch:focus {{
        border: 1px solid #6b9fe0;
        background-color: rgba(255,255,255,245);
    }}

    QPushButton#topbarIconButton,
    QPushButton#avisoButton,
    QPushButton#helpButton {{
        min-height: 34px;
        border-radius: 10px;
        padding: 0 12px;
        background-color: rgba(255,255,255,185);
        border: 1px solid rgba(199,213,230,190);
        color: #385778;
        font-weight: 600;
    }}

    QPushButton#topbarIconButton:hover,
    QPushButton#avisoButton:hover,
    QPushButton#helpButton:hover {{
        background-color: rgba(255,255,255,235);
        color: #0b63c7;
    }}

    QLabel#userBlock {{
        background: transparent;
        color: #2d4e72;
        font-weight: 700;
    }}

    QStackedWidget#mainStack {{
        background: transparent;
        border: none;
    }}

    QFrame#statusbar {{
        background: transparent;
        color: #70839b;
        border: none;
    }}

    QWidget#dashboardPage,
    QWidget#customerLedgerPage {{
        background: transparent;
    }}

    QLabel#heading,
    QLabel#customerLedgerTitle {{
        background: transparent;
        color: #17345a;
        font-size: 28px;
        font-weight: 700;
    }}

    QLabel#subheading,
    QLabel#customerLedgerSubtitle {{
        background: transparent;
        color: #6c7f98;
        font-size: 12px;
    }}

    QFrame#card,
    QFrame#dashboardOverduePanel,
    QFrame#dashboardUpcomingPanel,
    QFrame#customerLedgerClientsPanel,
    QFrame#customerLedgerDetailPanel,
    QFrame#customerLedgerHeaderCard {{
        background-color: rgba(255,255,255,205);
        border: 1px solid rgba(255,255,255,230);
        border-radius: 18px;
    }}

    QLabel#cardValue,
    QLabel#customerLedgerBalanceValue {{
        color: #17345a;
        font-size: 25px;
        font-weight: 700;
        background: transparent;
    }}

    QTableWidget#dashboardOverdueTable,
    QTableWidget#dashboardUpcomingTable,
    QTableWidget#customerLedgerClientsTable,
    QTableWidget#customerLedgerMovementsTable {{
        background-color: rgba(255,255,255,205);
        alternate-background-color: rgba(246,249,253,205);
        border: 1px solid rgba(204,216,230,190);
        border-radius: 12px;
        gridline-color: transparent;
        color: #294b70;
        selection-background-color: #e1eefc;
        selection-color: #14365e;
    }}

    QHeaderView::section {{
        background-color: rgba(236,243,251,230);
        color: #4c6687;
        border: none;
        border-bottom: 1px solid #d9e3ef;
        padding: 8px 7px;
        font-weight: 700;
    }}

    QWidget#customerLedgerPage QLineEdit {{
        min-height: 38px;
        background-color: rgba(255,255,255,225);
        border: 1px solid #cedbea;
        border-radius: 10px;
        padding: 0 12px;
        color: #294b70;
    }}


    /* Familia visual para modales y diálogos */
    QDialog {{
        background-color: #f5f8fc;
        color: #17345a;
    }}

    QDialog QLabel {{
        color: #294b70;
        background: transparent;
    }}

    QDialog QPushButton,
    QDialog QToolButton {{
        min-height: 38px;
        border-radius: 10px;
        padding: 0 14px;
        background-color: rgba(255,255,255,235);
        border: 1px solid #cbd9e8;
        color: #31557e;
        font-weight: 600;
    }}

    QDialog QPushButton:hover,
    QDialog QToolButton:hover {{
        background-color: #ffffff;
        border-color: #9ab9de;
        color: #0b63c7;
    }}

    QDialog QPushButton:pressed,
    QDialog QToolButton:pressed {{
        background-color: #e8f2fd;
        border-color: #86acd8;
    }}

    QDialog QPushButton:disabled,
    QDialog QToolButton:disabled {{
        background-color: #e9eef4;
        border-color: #d1dbe6;
        color: #8a9aac;
    }}

    QDialog QPushButton[uiRole="primary"],
    QDialog QToolButton[uiRole="primary"] {{
        background-color: #1473e6;
        border: 1px solid #1473e6;
        color: white;
        font-weight: 700;
    }}

    QDialog QPushButton[uiRole="primary"]:hover,
    QDialog QToolButton[uiRole="primary"]:hover {{
        background-color: #0f68cf;
        border-color: #0f68cf;
        color: white;
    }}

    QDialog QPushButton[uiRole="danger"],
    QDialog QToolButton[uiRole="danger"] {{
        background-color: #fff5f6;
        border: 1px solid #efc5cb;
        color: #b4233c;
    }}

    QDialog QLineEdit,
    QDialog QComboBox,
    QDialog QDateEdit,
    QDialog QSpinBox,
    QDialog QDoubleSpinBox,
    QDialog QTextEdit {{
        min-height: 36px;
        border-radius: 10px;
        border: 1px solid #cbd9e8;
        background-color: rgba(255,255,255,240);
        color: #294b70;
        padding: 0 10px;
    }}

    QDialog QLineEdit:focus,
    QDialog QComboBox:focus,
    QDialog QDateEdit:focus,
    QDialog QSpinBox:focus,
    QDialog QDoubleSpinBox:focus,
    QDialog QTextEdit:focus {{
        border: 1px solid #78a5da;
        background-color: #ffffff;
    }}

    QDialog QTableWidget {{
        background-color: rgba(255,255,255,235);
        alternate-background-color: rgba(246,249,253,235);
        border: 1px solid #d6e0ec;
        border-radius: 12px;
        gridline-color: transparent;
        color: #294b70;
        selection-background-color: #e1eefc;
        selection-color: #14365e;
    }}

    QDialog QTabWidget::pane {{
        border: 1px solid #d6e0ec;
        border-radius: 10px;
        background-color: rgba(255,255,255,210);
        top: -1px;
    }}

    QDialog QTabBar::tab {{
        background-color: rgba(255,255,255,190);
        color: #496582;
        border: 1px solid #d6e0ec;
        padding: 8px 14px;
        min-width: 120px;
    }}

    QDialog QTabBar::tab:selected {{
        background-color: #ffffff;
        color: #0b63c7;
        font-weight: 700;
    }}

    /* Familia visual única de botones dentro del área de trabajo */
    QStackedWidget#mainStack QPushButton,
    QStackedWidget#mainStack QToolButton {{
        min-height: 38px;
        border-radius: 10px;
        padding: 0 14px;
        background-color: rgba(255,255,255,220);
        border: 1px solid #cbd9e8;
        color: #31557e;
        font-weight: 600;
    }}

    QStackedWidget#mainStack QPushButton:hover,
    QStackedWidget#mainStack QToolButton:hover {{
        background-color: rgba(255,255,255,245);
        border-color: #9ab9de;
        color: #0b63c7;
    }}

    QStackedWidget#mainStack QPushButton:pressed,
    QStackedWidget#mainStack QToolButton:pressed {{
        background-color: #e8f2fd;
        border-color: #86acd8;
    }}

    QStackedWidget#mainStack QPushButton:disabled,
    QStackedWidget#mainStack QToolButton:disabled {{
        background-color: rgba(230,236,243,220);
        border-color: rgba(207,218,230,200);
        color: #8a9aac;
    }}

    QStackedWidget#mainStack QPushButton[uiRole="primary"],
    QStackedWidget#mainStack QToolButton[uiRole="primary"] {{
        background-color: #1473e6;
        border: 1px solid #1473e6;
        color: white;
        font-weight: 700;
    }}

    QStackedWidget#mainStack QPushButton[uiRole="primary"]:hover,
    QStackedWidget#mainStack QToolButton[uiRole="primary"]:hover {{
        background-color: #0f68cf;
        border-color: #0f68cf;
        color: white;
    }}

    QStackedWidget#mainStack QPushButton[uiRole="secondary"],
    QStackedWidget#mainStack QToolButton[uiRole="secondary"] {{
        background-color: rgba(255,255,255,220);
        border: 1px solid #cbd9e8;
        color: #31557e;
    }}

    QStackedWidget#mainStack QPushButton[uiRole="danger"],
    QStackedWidget#mainStack QToolButton[uiRole="danger"] {{
        background-color: rgba(255,245,246,225);
        border: 1px solid #efc5cb;
        color: #b4233c;
    }}

    QWidget#customerLedgerPage QPushButton,
    QWidget#customerLedgerPage QToolButton {{
        min-height: 38px;
        border-radius: 10px;
        padding: 0 14px;
        background-color: rgba(255,255,255,220);
        border: 1px solid #cbd9e8;
        color: #31557e;
        font-weight: 600;
    }}

    QPushButton#customerLedgerRegisterPaymentButton {{
        background-color: #1473e6;
        color: white;
        border: none;
        font-weight: 700;
    }}
    """