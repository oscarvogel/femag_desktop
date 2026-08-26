import hashlib
import hmac
import os

from peewee import IntegrityError, fn

from app.models.security import User, UserProfile
from app.services.audit_service import AuditService


class AuthService:
    CASE_INSENSITIVE_HASH_PREFIX = "ci$"

    def __init__(self, audit_service: AuditService | None = None):
        self.audit_service = audit_service or AuditService()

    def _hash_password(self, password: str, salt: bytes | None = None) -> str:
        salt = salt or os.urandom(16)
        normalized_password = password.casefold()
        digest = hashlib.pbkdf2_hmac(
            "sha256", normalized_password.encode("utf-8"), salt, 120_000
        )
        return f"{self.CASE_INSENSITIVE_HASH_PREFIX}{salt.hex()}:{digest.hex()}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            case_insensitive = stored_hash.startswith(self.CASE_INSENSITIVE_HASH_PREFIX)
            encoded_hash = (
                stored_hash.removeprefix(self.CASE_INSENSITIVE_HASH_PREFIX)
                if case_insensitive
                else stored_hash
            )
            salt_hex, digest_hex = encoded_hash.split(":", 1)
            candidate = password.casefold() if case_insensitive else password
            expected = hashlib.pbkdf2_hmac(
                "sha256", candidate.encode("utf-8"), bytes.fromhex(salt_hex), 120_000
            ).hex()
        except (AttributeError, TypeError, ValueError):
            return False
        return hmac.compare_digest(expected, digest_hex)

    def _upgrade_legacy_password_hash(self, user: User, password: str) -> None:
        if user.password_hash.startswith(self.CASE_INSENSITIVE_HASH_PREFIX):
            return
        user.password_hash = self._hash_password(password)
        user.save(only=[User.password_hash])

    @staticmethod
    def validate_password(password: str, confirmation: str | None = None) -> str:
        if not isinstance(password, str) or not password:
            raise ValueError("La contraseña es obligatoria.")
        if confirmation is not None and password != confirmation:
            raise ValueError("La confirmación de contraseña no coincide.")
        return password

    @staticmethod
    def normalize_username(username: str) -> str:
        username = (username or "").strip()
        if not username:
            raise ValueError("El usuario es obligatorio.")
        if any(character.isspace() for character in username):
            raise ValueError("El usuario no puede contener espacios.")
        return username

    @staticmethod
    def _find_user_case_insensitive(
        username: str,
        *,
        active_only: bool = False,
    ) -> User | None:
        normalized = (username or "").strip().casefold()
        if not normalized:
            return None
        query = User.select()
        if active_only:
            query = query.where(User.active == True)  # noqa: E712
        matches = [user for user in query if user.username.casefold() == normalized]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _username_exists_case_insensitive(
        username: str,
        *,
        exclude_user_id: int | None = None,
    ) -> bool:
        normalized = username.casefold()
        return any(
            user.username.casefold() == normalized
            for user in User.select()
            if exclude_user_id is None or user.id != exclude_user_id
        )

    @staticmethod
    def _profile(profile_name: str) -> UserProfile:
        profile_name = (profile_name or "").strip()
        if not profile_name:
            raise ValueError("Seleccione un perfil válido.")
        from app.services.permission_service import canonical_profile_name

        profile_name = canonical_profile_name(profile_name)
        profile, _ = UserProfile.get_or_create(name=profile_name)
        return profile

    def create_user(
        self,
        username: str,
        password: str,
        profile_name: str,
        *,
        display_name: str | None = None,
        actor: str | None = None,
        active: bool = True,
    ) -> User:
        if isinstance(actor, User):
            from app.services.permission_service import PermissionService

            PermissionService().require_administrator(actor)
        username = self.normalize_username(username)
        self.validate_password(password)
        profile = self._profile(profile_name)
        actor_name = actor.username if isinstance(actor, User) else actor
        if self._username_exists_case_insensitive(username):
            raise ValueError("Ya existe un usuario con ese nombre.")
        try:
            user = User.create(
                username=username,
                display_name=(display_name or "").strip() or None,
                password_hash=self._hash_password(password),
                profile=profile,
                active=active,
            )
        except IntegrityError as exc:
            raise ValueError("Ya existe un usuario con ese nombre.") from exc
        self.audit_service.record(
            user=actor_name or username,
            module="Sistema",
            action="crear usuario",
            record_ref=f"User:{user.id}",
            new_value={
                "username": username,
                "display_name": user.display_name,
                "profile": profile.name,
                "active": user.active,
            },
        )
        return user

    def create_initial_admin(self, username: str, password: str, *, display_name: str | None = None) -> User:
        if User.select().exists():
            raise ValueError("Ya existe al menos un usuario. El administrador inicial ya fue creado.")
        from app.services.permission_service import PermissionService

        PermissionService().seed_defaults()
        return self.create_user(
            username,
            password,
            "Administrador",
            display_name=display_name,
            actor="bootstrap",
        )

    def update_user(
        self,
        user: User,
        *,
        username: str,
        profile_name: str,
        display_name: str | None = None,
        active: bool,
        actor: User | str | None = None,
    ) -> User:
        user = User.get_by_id(user.id)
        if not isinstance(actor, User):
            raise PermissionError("La gestión de usuarios requiere un administrador habilitado.")
        from app.services.permission_service import PermissionService

        PermissionService().require_administrator(actor)
        username = self.normalize_username(username)
        profile = self._profile(profile_name)
        actor_name = actor.username if isinstance(actor, User) else actor
        if user.active and not active and self._is_last_active_administrator(user):
            raise ValueError("No se puede deshabilitar al último administrador habilitado.")
        if user.profile.name.strip().lower() == "administrador" and profile.name.strip().lower() != "administrador":
            if user.active and self._is_last_active_administrator(user):
                raise ValueError("No se puede quitar el perfil del último administrador habilitado.")
        if actor.id == user.id and user.active and not active:
            raise ValueError("No puede deshabilitar la sesión actual.")
        if (
            actor.id == user.id
            and user.profile.name.strip().lower() != profile.name.strip().lower()
        ):
            raise ValueError("No puede cambiar el perfil de la sesión actual.")
        if self._username_exists_case_insensitive(username, exclude_user_id=user.id):
            raise ValueError("Ya existe un usuario con ese nombre.")
        old_value = {
            "username": user.username,
            "display_name": user.display_name,
            "profile": user.profile.name,
            "active": user.active,
        }
        user.username = username
        user.display_name = (display_name or "").strip() or None
        user.profile = profile
        user.active = bool(active)
        user.save()
        new_value = {
            "username": user.username,
            "display_name": user.display_name,
            "profile": user.profile.name,
            "active": user.active,
        }
        audit_actions = []
        if old_value["active"] != new_value["active"]:
            audit_actions.append("habilitar usuario" if user.active else "deshabilitar usuario")
        if old_value["profile"] != new_value["profile"]:
            audit_actions.append("cambiar perfil usuario")
        if (
            old_value["username"] != new_value["username"]
            or old_value["display_name"] != new_value["display_name"]
        ):
            audit_actions.append("modificar usuario")
        if not audit_actions:
            audit_actions.append("modificar usuario")
        for action in audit_actions:
            self.audit_service.record(
                user=actor_name or user.username,
                module="Sistema",
                action=action,
                record_ref=f"User:{user.id}",
                old_value=old_value,
                new_value=new_value,
            )
        return user

    def set_active(self, user: User, active: bool, *, actor: User | str | None = None) -> User:
        return self.update_user(
            user,
            username=user.username,
            display_name=user.display_name,
            profile_name=user.profile.name,
            active=active,
            actor=actor,
        )

    def change_password(
        self,
        user: User,
        password: str,
        confirmation: str,
        *,
        actor: User | str | None = None,
        reset: bool = False,
    ) -> User:
        user = User.get_by_id(user.id)
        actor = actor or user
        if not isinstance(actor, User):
            raise PermissionError("La gestión de contraseñas requiere un usuario autenticado.")
        from app.services.permission_service import PermissionService

        if reset:
            PermissionService().require_administrator(actor)
        elif actor.id != user.id:
            raise PermissionError("Solo puede cambiar su propia contraseña.")
        self.validate_password(password, confirmation)
        user.password_hash = self._hash_password(password)
        user.save()
        actor_name = actor.username if isinstance(actor, User) else actor
        self.audit_service.record(
            user=actor_name or user.username,
            module="Sistema",
            action="restablecer contraseña" if reset else "cambiar contraseña",
            record_ref=f"User:{user.id}",
            new_value={"username": user.username},
        )
        return user

    @staticmethod
    def _is_last_active_administrator(user: User) -> bool:
        return (
            user.active
            and user.profile.name.strip().lower() == "administrador"
            and User.select()
            .join(UserProfile)
            .where(
                User.active == True,  # noqa: E712
                fn.LOWER(UserProfile.name) == "administrador",
            )
            .count()
            <= 1
        )

    def authenticate(self, username: str, password: str) -> User | None:
        username = (username or "").strip()
        user = self._find_user_case_insensitive(username, active_only=True)
        if user and self._verify_password(password, user.password_hash):
            self._upgrade_legacy_password_hash(user, password)
            self.audit_service.record(user=user.username, module="Sistema", action="login exitoso")
            return user
        self.audit_service.record(user=username, module="Sistema", action="login fallido")
        return None

    def authorize_administrator(self, username: str, password: str) -> User | None:
        username = (username or "").strip()
        user = self._find_user_case_insensitive(username, active_only=True)
        valid_password = False
        if user is not None:
            try:
                valid_password = self._verify_password(password, user.password_hash)
            except (TypeError, ValueError):
                valid_password = False
        is_administrator = bool(
            user is not None
            and user.profile.name.strip().lower() == "administrador"
        )
        authorized = user if valid_password and is_administrator else None
        if authorized is not None:
            self._upgrade_legacy_password_hash(authorized, password)
        self.audit_service.record(
            user=authorized.username if authorized is not None else username or None,
            module="Sistema",
            action=(
                "autorizar administrador"
                if authorized is not None
                else "rechazar autorizacion administrador"
            ),
            record_ref=f"User:{user.id}" if user is not None else None,
        )
        return authorized
