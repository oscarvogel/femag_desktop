import hashlib
import hmac
import os

from app.models.security import User, UserProfile
from app.services.audit_service import AuditService


class AuthService:
    def __init__(self, audit_service: AuditService | None = None):
        self.audit_service = audit_service or AuditService()

    def _hash_password(self, password: str, salt: bytes | None = None) -> str:
        salt = salt or os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return f"{salt.hex()}:{digest.hex()}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        salt_hex, digest_hex = stored_hash.split(":", 1)
        expected = self._hash_password(password, bytes.fromhex(salt_hex)).split(":", 1)[1]
        return hmac.compare_digest(expected, digest_hex)

    def create_user(self, username: str, password: str, profile_name: str) -> User:
        profile, _ = UserProfile.get_or_create(name=profile_name)
        user = User.create(
            username=username,
            password_hash=self._hash_password(password),
            profile=profile,
        )
        self.audit_service.record(
            user=username,
            module="Sistema",
            action="crear usuario",
            record_ref=f"User:{user.id}",
            new_value={"username": username, "profile": profile_name},
        )
        return user

    def authenticate(self, username: str, password: str) -> User | None:
        user = User.get_or_none(User.username == username, User.active == True)  # noqa: E712
        if user and self._verify_password(password, user.password_hash):
            self.audit_service.record(user=username, module="Sistema", action="login exitoso")
            return user
        self.audit_service.record(user=username, module="Sistema", action="login fallido")
        return None
