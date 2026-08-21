import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_managerial_dashboard_page_renders_v1_sections(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QPushButton, QTableWidget

    from app.ui.managerial_dashboard import ManagerialDashboardPage

    app = QApplication.instance() or QApplication([])
    page = ManagerialDashboardPage()
    page.show()
    app.processEvents()

    assert page.objectName() == "managerialDashboardPage"
    period = page.findChild(QComboBox, "managerialPeriodPreset")
    refresh = page.findChild(QPushButton, "managerialRefreshButton")
    clients = page.findChild(QTableWidget, "managerialTopClients")
    products = page.findChild(QTableWidget, "managerialTopProducts")
    evolution = page.findChild(QTableWidget, "managerialMonthlyEvolution")
    statuses = page.findChild(QTableWidget, "managerialOrderStatuses")

    assert period is not None
    assert period.currentData() == "este mes"
    assert refresh is not None and refresh.isEnabled()
    assert clients is not None
    assert products is not None
    assert evolution is not None
    assert statuses is not None
    assert evolution.rowCount() == 12

    page.close()
