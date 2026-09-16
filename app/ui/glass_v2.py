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

    QScrollArea#dashboardScrollArea {{
        background: transparent;
        border: none;
    }}

    QWidget#dashboardPage {{
        background-color: rgba(242, 248, 250, 106);
        border: 1px solid rgba(255, 255, 255, 110);
        border-radius: 22px;
    }}

    QLabel#dashboardEyebrow {{
        color: #6a836d;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.2px;
        background: transparent;
    }}

    QLabel#dashboardHeading {{
        color: #173d4b;
        font-size: 30px;
        font-weight: 700;
        background: transparent;
    }}

    QLabel#dashboardSubheading {{
        color: #617980;
        font-size: 13px;
        background: transparent;
    }}

    QFrame#dashboardQuickActions {{
        background-color: rgba(255, 255, 255, 174);
        border: 1px solid rgba(255, 255, 255, 225);
        border-radius: 18px;
    }}

    QLabel#dashboardQuickActionsTitle {{
        color: #254d5b;
        font-size: 13px;
        font-weight: 700;
        background: transparent;
    }}

    QFrame#dashboardQuickActions QPushButton {{
        min-height: 38px;
        border-radius: 10px;
        padding: 0 12px;
        background-color: rgba(250, 253, 253, 205);
        border: 1px solid rgba(191, 210, 215, 205);
        color: #315969;
        font-size: 12px;
        font-weight: 600;
    }}

    QFrame#dashboardQuickActions QPushButton:hover {{
        background-color: rgba(255, 255, 255, 245);
        border-color: #8ab1b5;
        color: #17636c;
    }}

    QPushButton#dashboardNuevaordendecarga {{
        background-color: #167a76;
        border: 1px solid #167a76;
        color: white;
        font-weight: 700;
    }}

    QPushButton#dashboardNuevaordendecarga:hover {{
        background-color: #0e6966;
        border-color: #0e6966;
        color: white;
    }}

    QFrame#dashboardQuickActions QPushButton[dashboardState="planned"] {{
        background-color: rgba(242, 244, 241, 175);
        border: 1px dashed rgba(150, 164, 153, 180);
        color: #849189;
        font-weight: 600;
    }}

    QFrame#dashboardQuickActions QPushButton[dashboardState="planned"]:disabled {{
        background-color: rgba(242, 244, 241, 175);
        border: 1px dashed rgba(150, 164, 153, 180);
        color: #849189;
    }}

    QFrame#dashboardMetricCard {{
        min-height: 92px;
        background-color: rgba(255, 255, 255, 183);
        border: 1px solid rgba(255, 255, 255, 228);
        border-radius: 16px;
    }}

    QFrame#dashboardMetricCard:hover {{
        background-color: rgba(255, 255, 255, 220);
        border-color: rgba(159, 193, 192, 215);
    }}

    QLabel#dashboardMetricLabel {{
        color: #71868b;
        font-size: 11px;
        font-weight: 600;
        background: transparent;
    }}

    QLabel#dashboardMetricValue {{
        color: #173d4b;
        font-size: 23px;
        font-weight: 700;
        background: transparent;
    }}

    QLabel#dashboardCollectionsTitle {{
        color: #254d5b;
        font-size: 17px;
        font-weight: 700;
        margin-top: 6px;
        background: transparent;
    }}

    QPushButton#dashboardOverdueBudgetsCard,
    QPushButton#dashboardDueTodayCard,
    QPushButton#dashboardNext7Card,
    QPushButton#dashboardNext30Card,
    QPushButton#dashboardDebtorBalanceCard {{
        text-align: left;
        padding: 12px 13px;
        border-radius: 14px;
        font-size: 12px;
        font-weight: 700;
    }}

    QPushButton#dashboardOverdueBudgetsCard {{
        color: #9f3043;
        background-color: rgba(255, 244, 245, 205);
        border: 1px solid rgba(235, 191, 199, 210);
    }}

    QPushButton#dashboardDueTodayCard {{
        color: #a55c16;
        background-color: rgba(255, 248, 238, 207);
        border: 1px solid rgba(237, 207, 167, 215);
    }}

    QPushButton#dashboardNext7Card {{
        color: #8a690a;
        background-color: rgba(255, 252, 235, 207);
        border: 1px solid rgba(231, 217, 160, 215);
    }}

    QPushButton#dashboardNext30Card {{
        color: #2c629d;
        background-color: rgba(244, 249, 255, 207);
        border: 1px solid rgba(192, 213, 239, 215);
    }}

    QPushButton#dashboardDebtorBalanceCard {{
        color: #315969;
        background-color: rgba(247, 251, 250, 207);
        border: 1px solid rgba(196, 215, 215, 215);
    }}

    QPushButton#dashboardOverdueBudgetsCard:hover,
    QPushButton#dashboardDueTodayCard:hover,
    QPushButton#dashboardNext7Card:hover,
    QPushButton#dashboardNext30Card:hover,
    QPushButton#dashboardDebtorBalanceCard:hover {{
        background-color: rgba(255, 255, 255, 238);
        border-color: #83aaad;
    }}

    QLabel#dashboardPanelTitle {{
        color: #254d5b;
        font-size: 15px;
        font-weight: 700;
        background: transparent;
    }}

    QLabel#dashboardPanelCaption {{
        color: #7a9093;
        font-size: 11px;
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

    QFrame#dashboardOverduePanel,
    QFrame#dashboardUpcomingPanel {{
        background-color: rgba(255, 255, 255, 184);
        border: 1px solid rgba(255, 255, 255, 228);
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

    QTableWidget#dashboardOverdueTable,
    QTableWidget#dashboardUpcomingTable {{
        background-color: rgba(251, 253, 253, 188);
        alternate-background-color: rgba(238, 246, 245, 135);
        border: 1px solid rgba(199, 216, 218, 185);
        border-radius: 11px;
        color: #365965;
        selection-background-color: #dcefed;
        selection-color: #173d4b;
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

    /* Ordenes de carga: workspace + alta/edicion + pallets */
    QWidget#loadOrdersPage {{
        background-color: rgba(242,248,250,105);
        border: 1px solid rgba(255,255,255,110);
        border-radius: 22px;
    }}

    QWidget#loadOrdersPage QLabel#heading {{
        color: #173d4b;
        font-size: 30px;
        font-weight: 700;
        background: transparent;
    }}

    QWidget#loadOrdersPage QLabel#subheading {{
        color: #617980;
        font-size: 13px;
        background: transparent;
    }}

    QWidget#loadOrdersPage QFrame#contentPanel {{
        background-color: rgba(255,255,255,182);
        border: 1px solid rgba(255,255,255,225);
        border-radius: 18px;
    }}

    QWidget#loadOrdersPage QLineEdit#loadOrderSearchInput {{
        min-height: 40px;
        background-color: rgba(255,255,255,225);
        border: 1px solid rgba(195,211,226,210);
        border-radius: 11px;
        padding: 0 13px;
        color: #315969;
    }}

    QWidget#loadOrdersPage QFrame#loadOrderFilters {{
        background-color: rgba(255,255,255,165);
        border: 1px solid rgba(255,255,255,220);
        border-radius: 14px;
    }}

    QWidget#loadOrdersPage QLabel#loadOrderResultsLabel {{
        color: #6b8186;
        font-size: 11px;
        background: transparent;
        padding: 0 2px;
    }}

    QWidget#loadOrdersPage QCheckBox#loadOrderDateFilterEnabled {{
        color: #49686f;
        background: transparent;
        spacing: 6px;
    }}

    QWidget#loadOrdersPage QTableWidget#loadOrdersTable {{
        background-color: rgba(251,253,253,190);
        alternate-background-color: rgba(239,246,245,145);
        border: 1px solid rgba(199,216,218,190);
        border-radius: 12px;
        color: #365965;
        selection-background-color: #dcefed;
        selection-color: #173d4b;
    }}

    QWidget#loadOrdersPage QTableWidget#loadOrdersTable QHeaderView::section {{
        background-color: rgba(232,242,241,225);
        color: #476a70;
        border: none;
        border-bottom: 1px solid #d4e3e2;
        padding: 8px 7px;
        font-weight: 700;
    }}

    QDialog#loadOrderEntryDialog,
    QDialog#loadOrderPalletDialog {{
        background-color: #edf4f7;
        color: #173d4b;
    }}

    QDialog#loadOrderEntryDialog QLabel#dialogTitle,
    QDialog#loadOrderPalletDialog QLabel#dialogTitle {{
        color: #173d4b;
        font-size: 26px;
        font-weight: 700;
        background: transparent;
    }}

    QDialog#loadOrderEntryDialog QLabel#formHint,
    QDialog#loadOrderPalletDialog QLabel#formHint {{
        color: #698087;
        font-size: 12px;
        background: transparent;
    }}

    QDialog#loadOrderEntryDialog QFrame#loadOrderEntryStepList {{
        background-color: rgba(255,255,255,178);
        border: 1px solid rgba(255,255,255,225);
        border-radius: 16px;
    }}

    QDialog#loadOrderEntryDialog QLabel#loadOrderStepTitle {{
        color: #6a836d;
        font-size: 11px;
        font-weight: 700;
        background: transparent;
        padding: 4px 8px 8px 8px;
    }}

    QDialog#loadOrderEntryDialog QPushButton[stepNav="true"] {{
        min-height: 42px;
        text-align: left;
        padding: 0 12px;
        background-color: transparent;
        color: #49686f;
        border: 1px solid transparent;
        border-radius: 11px;
        font-weight: 600;
    }}

    QDialog#loadOrderEntryDialog QPushButton[stepNav="true"]:hover {{
        background-color: rgba(255,255,255,180);
        border-color: rgba(179,205,207,170);
    }}

    QDialog#loadOrderEntryDialog QPushButton[stepNav="true"]:checked {{
        background-color: rgba(220,239,237,235);
        border: 1px solid rgba(112,168,166,165);
        color: #17636c;
        font-weight: 700;
    }}

    QDialog#loadOrderEntryDialog QStackedWidget#loadOrderEntryStepStack {{
        background: transparent;
        border: none;
    }}

    QDialog#loadOrderEntryDialog QFrame#formSection {{
        background-color: rgba(255,255,255,190);
        border: 1px solid rgba(255,255,255,228);
        border-radius: 18px;
    }}

    QDialog#loadOrderEntryDialog QLabel#sectionTitle {{
        color: #254d5b;
        font-size: 16px;
        font-weight: 700;
        background: transparent;
    }}

    QDialog#loadOrderEntryDialog QTableWidget {{
        background-color: rgba(255,255,255,218);
        alternate-background-color: rgba(241,247,247,205);
        border: 1px solid rgba(200,216,218,195);
        border-radius: 11px;
        color: #365965;
        selection-background-color: #dcefed;
        selection-color: #173d4b;
    }}

    QDialog#loadOrderPalletDialog QWidget#palletCompositionWidget {{
        background: transparent;
    }}

    QDialog#loadOrderPalletDialog QLabel#palletCompositionTitle {{
        color: #173d4b;
        font-size: 20px;
        font-weight: 700;
        background: transparent;
    }}

    QDialog#loadOrderPalletDialog QFrame#palletEditorPanel {{
        background-color: rgba(255,255,255,185);
        border: 1px solid rgba(255,255,255,225);
        border-radius: 16px;
        padding: 8px;
    }}

    QDialog#loadOrderPalletDialog QFrame#loadOrderKgTotalFrame {{
        background-color: #176f70;
        border: 1px solid rgba(255,255,255,120);
        border-radius: 16px;
    }}

    QDialog#loadOrderPalletDialog QScrollArea#palletCardScroll,
    QDialog#loadOrderPalletDialog QScrollArea#palletEditorScroll {{
        background: transparent;
        border: none;
    }}

    QDialog#loadOrderPalletDialog QTabWidget#palletEditorTabs::pane {{
        border: 1px solid rgba(201,218,220,195);
        border-radius: 12px;
        background-color: rgba(255,255,255,175);
    }}

    QDialog#loadOrderPalletDialog QTabWidget#palletEditorTabs QTabBar::tab {{
        background-color: rgba(255,255,255,160);
        color: #49686f;
        border: 1px solid rgba(201,218,220,185);
        padding: 8px 12px;
    }}

    QDialog#loadOrderPalletDialog QTabWidget#palletEditorTabs QTabBar::tab:selected {{
        background-color: rgba(255,255,255,238);
        color: #17636c;
        font-weight: 700;
    }}

    /* Controles generales: una sola familia visual para todas las pantallas */
    QStackedWidget#mainStack QLineEdit,
    QStackedWidget#mainStack QComboBox,
    QStackedWidget#mainStack QDateEdit,
    QStackedWidget#mainStack QSpinBox,
    QStackedWidget#mainStack QDoubleSpinBox,
    QStackedWidget#mainStack QTextEdit {{
        min-height: 36px;
        border-radius: 10px;
        border: 1px solid #cbd9e8;
        background-color: rgba(255,255,255,225);
        color: #294b70;
        padding: 0 10px;
    }}

    QStackedWidget#mainStack QLineEdit:focus,
    QStackedWidget#mainStack QComboBox:focus,
    QStackedWidget#mainStack QDateEdit:focus,
    QStackedWidget#mainStack QSpinBox:focus,
    QStackedWidget#mainStack QDoubleSpinBox:focus,
    QStackedWidget#mainStack QTextEdit:focus {{
        border: 1px solid #78a5da;
        background-color: rgba(255,255,255,248);
    }}

    QStackedWidget#mainStack QTableWidget {{
        background-color: rgba(255,255,255,205);
        alternate-background-color: rgba(246,249,253,205);
        border: 1px solid rgba(204,216,230,190);
        border-radius: 12px;
        gridline-color: transparent;
        color: #294b70;
        selection-background-color: #e1eefc;
        selection-color: #14365e;
    }}

    QStackedWidget#mainStack QHeaderView::section {{
        background-color: rgba(236,243,251,230);
        color: #4c6687;
        border: none;
        border-bottom: 1px solid #d9e3ef;
        padding: 8px 7px;
        font-weight: 700;
    }}

    QStackedWidget#mainStack QTabWidget::pane {{
        border: 1px solid rgba(207,220,233,205);
        border-radius: 12px;
        background-color: rgba(255,255,255,175);
        top: -1px;
    }}

    QStackedWidget#mainStack QTabBar::tab {{
        background-color: rgba(255,255,255,155);
        color: #496582;
        border: 1px solid rgba(207,220,233,190);
        padding: 8px 14px;
        min-width: 110px;
    }}

    QStackedWidget#mainStack QTabBar::tab:selected {{
        background-color: rgba(255,255,255,235);
        color: #0b63c7;
        font-weight: 700;
    }}

    QStackedWidget#mainStack QGroupBox {{
        background-color: rgba(255,255,255,165);
        border: 1px solid rgba(205,218,232,190);
        border-radius: 14px;
        margin-top: 12px;
        padding-top: 10px;
        color: #31557e;
        font-weight: 600;
    }}

    QStackedWidget#mainStack QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: #31557e;
        background: transparent;
    }}

    QStackedWidget#mainStack QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}

    QStackedWidget#mainStack QScrollBar::handle:vertical {{
        background: rgba(116,143,171,125);
        border-radius: 5px;
        min-height: 26px;
    }}

    QStackedWidget#mainStack QScrollBar::add-line:vertical,
    QStackedWidget#mainStack QScrollBar::sub-line:vertical,
    QStackedWidget#mainStack QScrollBar::add-page:vertical,
    QStackedWidget#mainStack QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0;
    }}

    QStackedWidget#mainStack QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}

    QStackedWidget#mainStack QScrollBar::handle:horizontal {{
        background: rgba(116,143,171,125);
        border-radius: 5px;
        min-width: 26px;
    }}

    QStackedWidget#mainStack QScrollBar::add-line:horizontal,
    QStackedWidget#mainStack QScrollBar::sub-line:horizontal,
    QStackedWidget#mainStack QScrollBar::add-page:horizontal,
    QStackedWidget#mainStack QScrollBar::sub-page:horizontal {{
        background: transparent;
        width: 0;
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

    /* El dashboard tiene prioridad sobre la familia genérica del área de trabajo. */
    QFrame#dashboardQuickActions QPushButton {{
        background-color: rgba(250, 253, 253, 205);
        border: 1px solid rgba(191, 210, 215, 205);
        color: #315969;
    }}

    QFrame#dashboardQuickActions QPushButton[uiRole="primary"] {{
        background-color: #167a76;
        border: 1px solid #167a76;
        color: white;
    }}

    QFrame#dashboardQuickActions QPushButton[uiRole="primary"]:hover {{
        background-color: #0e6966;
        border-color: #0e6966;
        color: white;
    }}

    QFrame#dashboardQuickActions QPushButton[dashboardState="planned"]:disabled {{
        background-color: rgba(242, 244, 241, 175);
        border: 1px dashed rgba(150, 164, 153, 180);
        color: #849189;
    }}

    QStackedWidget#mainStack QPushButton#dashboardOverdueBudgetsCard,
    QStackedWidget#mainStack QPushButton#dashboardDueTodayCard,
    QStackedWidget#mainStack QPushButton#dashboardNext7Card,
    QStackedWidget#mainStack QPushButton#dashboardNext30Card,
    QStackedWidget#mainStack QPushButton#dashboardDebtorBalanceCard {{
        text-align: left;
        padding: 12px 13px;
        border-radius: 14px;
        font-size: 12px;
        font-weight: 700;
    }}

    QStackedWidget#mainStack QPushButton#dashboardOverdueBudgetsCard {{
        color: #9f3043;
        background-color: rgba(255, 244, 245, 205);
        border: 1px solid rgba(235, 191, 199, 210);
    }}

    QStackedWidget#mainStack QPushButton#dashboardDueTodayCard {{
        color: #a55c16;
        background-color: rgba(255, 248, 238, 207);
        border: 1px solid rgba(237, 207, 167, 215);
    }}

    QStackedWidget#mainStack QPushButton#dashboardNext7Card {{
        color: #8a690a;
        background-color: rgba(255, 252, 235, 207);
        border: 1px solid rgba(231, 217, 160, 215);
    }}

    QStackedWidget#mainStack QPushButton#dashboardNext30Card {{
        color: #2c629d;
        background-color: rgba(244, 249, 255, 207);
        border: 1px solid rgba(192, 213, 239, 215);
    }}

    QStackedWidget#mainStack QPushButton#dashboardDebtorBalanceCard {{
        color: #315969;
        background-color: rgba(247, 251, 250, 207);
        border: 1px solid rgba(196, 215, 215, 215);
    }}

    QStackedWidget#mainStack QPushButton#dashboardOverdueBudgetsCard:hover,
    QStackedWidget#mainStack QPushButton#dashboardDueTodayCard:hover,
    QStackedWidget#mainStack QPushButton#dashboardNext7Card:hover,
    QStackedWidget#mainStack QPushButton#dashboardNext30Card:hover,
    QStackedWidget#mainStack QPushButton#dashboardDebtorBalanceCard:hover {{
        background-color: rgba(255, 255, 255, 238);
        border-color: #83aaad;
    }}

    QTableWidget#dashboardOverdueTable QHeaderView::section,
    QTableWidget#dashboardUpcomingTable QHeaderView::section {{
        background-color: rgba(232, 242, 241, 225);
        color: #476a70;
        border: none;
        border-bottom: 1px solid #d4e3e2;
        padding: 8px 7px;
        font-weight: 700;
    }}
    """
