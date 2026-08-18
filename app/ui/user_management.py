from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.security import MenuItem, User, UserProfile
from app.services.auth_service import AuthService
from app.services.permission_service import ACTIONS, MENU, PermissionService
from app.ui.form_feedback import FormFeedback


class UserDialog(QDialog):
    def __init__(self, *, profiles: list[UserProfile], user: User | None = None, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Nuevo usuario" if user is None else "Editar usuario")
        self.setMinimumWidth(430)

        self.display_name = QLineEdit(user.display_name if user else "")
        self.display_name.setObjectName("userDisplayNameInput")
        self.username = QLineEdit(user.username if user else "")
        self.username.setObjectName("userUsernameInput")
        self.profile = QComboBox()
        self.profile.setObjectName("userProfileCombo")
        for profile in profiles:
            self.profile.addItem(profile.name, profile.id)
        if user:
            self.profile.setCurrentIndex(max(0, self.profile.findData(user.profile_id)))
        self.active = QCheckBox("Usuario habilitado")
        self.active.setObjectName("userActiveCheck")
        self.active.setChecked(user.active if user else True)

        layout = QFormLayout()
        layout.addRow("Nombre visible:", self.display_name)
        layout.addRow("Usuario:", self.username)
        layout.addRow("Perfil:", self.profile)
        layout.addRow("Estado:", self.active)

        self.password = None
        self.confirm_password = None
        if user is None:
            self.password = QLineEdit()
            self.password.setEchoMode(QLineEdit.Password)
            self.password.setObjectName("userPasswordInput")
            self.confirm_password = QLineEdit()
            self.confirm_password.setEchoMode(QLineEdit.Password)
            self.confirm_password.setObjectName("userPasswordConfirmationInput")
            layout.addRow("Contraseña inicial:", self.password)
            layout.addRow("Confirmar contraseña:", self.confirm_password)

        note = QLabel("Las contraseñas se almacenan únicamente como hash seguro.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addRow(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.setLayout(layout)

    def _validate(self) -> None:
        if not self.username.text().strip():
            QMessageBox.warning(self, "Usuario", "Complete el usuario.")
            return
        if self.profile.currentData() is None:
            QMessageBox.warning(self, "Usuario", "Seleccione un perfil.")
            return
        if self.user is None and (not self.password or not self.password.text()):
            QMessageBox.warning(self, "Contraseña", "La contraseña inicial es obligatoria.")
            return
        if self.user is None and self.password and self.password.text() != self.confirm_password.text():
            QMessageBox.warning(self, "Contraseña", "La confirmación no coincide.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "display_name": self.display_name.text().strip() or None,
            "username": self.username.text().strip(),
            "profile_name": self.profile.currentText(),
            "active": self.active.isChecked(),
            "password": self.password.text() if self.password is not None else None,
            "confirmation": self.confirm_password.text() if self.confirm_password is not None else None,
        }


class PasswordDialog(QDialog):
    def __init__(self, *, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(390)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setObjectName("newPasswordInput")
        self.confirmation = QLineEdit()
        self.confirmation.setEchoMode(QLineEdit.Password)
        self.confirmation.setObjectName("newPasswordConfirmationInput")
        form = QFormLayout()
        form.addRow("Nueva contraseña:", self.password)
        form.addRow("Confirmar contraseña:", self.confirmation)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setLayout(form)

    def _validate(self) -> None:
        try:
            AuthService.validate_password(self.password.text(), self.confirmation.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Contraseña", str(exc))
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self.password.text(), self.confirmation.text()


class InitialAdminDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear administrador inicial")
        self.setMinimumWidth(430)
        self.display_name = QLineEdit()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.confirmation = QLineEdit()
        self.confirmation.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow(QLabel("No existen usuarios. Cree el administrador inicial para comenzar."))
        form.addRow("Nombre visible:", self.display_name)
        form.addRow("Usuario:", self.username)
        form.addRow("Contraseña:", self.password)
        form.addRow("Confirmar contraseña:", self.confirmation)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setLayout(form)

    def _validate(self) -> None:
        try:
            AuthService.normalize_username(self.username.text())
            AuthService.validate_password(self.password.text(), self.confirmation.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Administrador inicial", str(exc))
            return
        self.accept()

    def values(self) -> dict[str, str | None]:
        return {
            "display_name": self.display_name.text().strip() or None,
            "username": self.username.text().strip(),
            "password": self.password.text(),
        }


class UserManagementPage(QWidget):
    def __init__(self, *, user: User, parent=None):
        super().__init__(parent)
        self.current_user = user
        self.auth = AuthService()
        self.permissions = PermissionService()
        self._is_admin = self.permissions.is_administrator(user)
        self._permission_checkboxes: dict[tuple[int, str], QCheckBox] = {}
        self.setObjectName("userManagementPage")
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("Usuarios, perfiles y permisos")
        title.setObjectName("userManagementTitle")
        subtitle = QLabel("Administre el acceso operativo y audite los cambios de seguridad.")
        subtitle.setStyleSheet("color: #64748b;")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("userManagementTabs")
        self.tabs.addTab(self._users_tab(), "Usuarios")
        self.tabs.addTab(self._permissions_tab(), "Perfiles y permisos")
        root.addWidget(self.tabs, 1)

    def _users_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        actions = QHBoxLayout()
        self.new_user_button = QPushButton("Nuevo usuario")
        self.edit_user_button = QPushButton("Editar")
        self.toggle_user_button = QPushButton("Habilitar / deshabilitar")
        self.reset_password_button = QPushButton("Restablecer contraseña")
        for button in (self.new_user_button, self.edit_user_button, self.toggle_user_button, self.reset_password_button):
            button.setEnabled(self._is_admin)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.users_table = QTableWidget(0, 4)
        self.users_table.setObjectName("usersTable")
        self.users_table.setHorizontalHeaderLabels(["Nombre", "Usuario", "Perfil", "Estado"])
        self.users_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.users_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.users_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.users_table, 1)
        self.users_feedback = FormFeedback("usersFeedback")
        layout.addWidget(self.users_feedback)

        self.new_user_button.clicked.connect(self._new_user)
        self.edit_user_button.clicked.connect(self._edit_user)
        self.toggle_user_button.clicked.connect(self._toggle_user)
        self.reset_password_button.clicked.connect(self._reset_password)
        self._refresh_users()
        return page

    def _permissions_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        header = QHBoxLayout()
        header.addWidget(QLabel("Perfil:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("permissionsProfileCombo")
        for profile in UserProfile.select().order_by(UserProfile.name):
            self.profile_combo.addItem(profile.name, profile.id)
        header.addWidget(self.profile_combo)
        header.addStretch(1)
        self.save_permissions_button = QPushButton("Guardar permisos")
        self.save_permissions_button.setEnabled(self._is_admin)
        header.addWidget(self.save_permissions_button)
        layout.addLayout(header)

        note = QLabel("Los cambios se aplican por perfil y quedan registrados en auditoría. Se recomienda revisar antes de guardar.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b;")
        layout.addWidget(note)

        self.permissions_table = QTableWidget()
        self.permissions_table.setObjectName("permissionsTable")
        self.permissions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.permissions_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.permissions_table, 1)
        self.permissions_feedback = FormFeedback("permissionsFeedback")
        layout.addWidget(self.permissions_feedback)

        self.profile_combo.currentIndexChanged.connect(self._load_permissions)
        self.save_permissions_button.clicked.connect(self._save_permissions)
        self._load_permissions()
        return page

    def _refresh_users(self) -> None:
        users = list(User.select().join(UserProfile).order_by(User.username))
        self.users_table.setRowCount(len(users))
        for row, user in enumerate(users):
            values = [user.display_name or "-", user.username, user.profile.name, "Habilitado" if user.active else "Deshabilitado"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, user.id)
                self.users_table.setItem(row, column, item)
        if users:
            self.users_table.selectRow(0)

    def _selected_user(self) -> User | None:
        row = self.users_table.currentRow()
        item = self.users_table.item(row, 0)
        if item is None:
            return None
        return User.get_or_none(User.id == item.data(Qt.UserRole))

    def _profiles(self) -> list[UserProfile]:
        return list(UserProfile.select().order_by(UserProfile.name))

    def _new_user(self) -> None:
        dialog = UserDialog(profiles=self._profiles(), parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        try:
            self.auth.create_user(
                values["username"],
                values["password"],
                values["profile_name"],
                display_name=values["display_name"],
                actor=self.current_user,
                active=values["active"],
            )
        except (ValueError, TypeError, PermissionError) as exc:
            self.users_feedback.show_error(str(exc))
            return
        self._refresh_users()
        self.users_feedback.show_success("Usuario creado correctamente.")

    def _edit_user(self) -> None:
        user = self._selected_user()
        if user is None:
            self.users_feedback.show_warning("Seleccione un usuario.", focus_widget=self.users_table)
            return
        dialog = UserDialog(profiles=self._profiles(), user=user, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        try:
            self.auth.update_user(user, actor=self.current_user, **{key: values[key] for key in ("username", "profile_name", "display_name", "active")})
        except (ValueError, TypeError, PermissionError) as exc:
            self.users_feedback.show_error(str(exc), focus_widget=self.users_table)
            return
        self._refresh_users()
        self.users_feedback.show_success("Usuario actualizado correctamente.")

    def _toggle_user(self) -> None:
        user = self._selected_user()
        if user is None:
            self.users_feedback.show_warning("Seleccione un usuario.", focus_widget=self.users_table)
            return
        target_state = not user.active
        try:
            self.auth.set_active(user, target_state, actor=self.current_user)
        except (ValueError, PermissionError) as exc:
            self.users_feedback.show_error(str(exc), focus_widget=self.users_table)
            return
        self._refresh_users()
        self.users_feedback.show_success("Estado de usuario actualizado.")

    def _reset_password(self) -> None:
        user = self._selected_user()
        if user is None:
            self.users_feedback.show_warning("Seleccione un usuario.", focus_widget=self.users_table)
            return
        dialog = PasswordDialog(title=f"Restablecer contraseña: {user.username}", parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        password, confirmation = dialog.values()
        try:
            self.auth.change_password(user, password, confirmation, actor=self.current_user, reset=True)
        except (ValueError, PermissionError) as exc:
            self.users_feedback.show_error(str(exc), focus_widget=self.users_table)
            return
        self.users_feedback.show_success(
            "Contraseña restablecida. Comuníquela por un canal seguro."
        )

    def _load_permissions(self) -> None:
        self._permission_checkboxes.clear()
        profile_id = self.profile_combo.currentData()
        if profile_id is None:
            return
        profile = UserProfile.get_by_id(profile_id)
        menu_items = list(MenuItem.select().order_by(MenuItem.section, MenuItem.sort_order, MenuItem.title))
        self.permissions_table.setRowCount(len(menu_items))
        self.permissions_table.setColumnCount(2 + len(ACTIONS))
        self.permissions_table.setHorizontalHeaderLabels(["Módulo", "Pantalla"] + [action.title() for action in ACTIONS])
        current = self.permissions.permissions_for_profile(profile)
        for row, item in enumerate(menu_items):
            self.permissions_table.setItem(row, 0, QTableWidgetItem(item.section))
            self.permissions_table.setItem(row, 1, QTableWidgetItem(item.title))
            for offset, action in enumerate(ACTIONS, start=2):
                checkbox = QCheckBox()
                checkbox.setChecked(current.get((item.id, action), False))
                checkbox.setProperty("menu_item_id", item.id)
                checkbox.setProperty("action", action)
                self.permissions_table.setCellWidget(row, offset, checkbox)
                self._permission_checkboxes[(item.id, action)] = checkbox
        self.permissions_table.resizeColumnsToContents()

    def _save_permissions(self) -> None:
        profile_id = self.profile_combo.currentData()
        if profile_id is None:
            return
        profile = UserProfile.get_by_id(profile_id)
        if QMessageBox.warning(
            self,
            "Confirmar permisos",
            f"¿Guardar los permisos del perfil {profile.name}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        values = {key: checkbox.isChecked() for key, checkbox in self._permission_checkboxes.items()}
        try:
            changed = self.permissions.update_profile_permissions(self.current_user, profile, values)
        except PermissionError as exc:
            self.permissions_feedback.show_error(str(exc), focus_widget=self.permissions_table)
            return
        self.permissions_feedback.show_success(f"Permisos actualizados: {changed} cambio(s).")


class ChangePasswordDialog(PasswordDialog):
    pass
