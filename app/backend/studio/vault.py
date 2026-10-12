from __future__ import annotations

import os
import platform

from cryptography.fernet import Fernet

from .database import Database
from .models import StudioError


class Vault:
    """Credentials stay server-side. Keychain is preferred; fallback is explicit."""

    def __init__(self, db: Database, *, use_keychain: bool = True):
        self.db = db
        self.mode = "encrypted_file"
        path = db.root / ".vault-key"
        with db.connect() as c:
            saved = c.execute("SELECT value FROM meta WHERE key='vault_mode'").fetchone()
            has_secrets = bool(c.execute('SELECT COUNT(*) FROM secrets').fetchone()[0])
        prior = saved[0] if saved else ('encrypted_file' if path.exists() else None)
        key = None
        if prior != 'encrypted_file' and use_keychain and platform.system() == "Darwin":
            import keyring
            try:
                key = keyring.get_password("director-studio-vault", str(db.root))
                if key is None:
                    if prior == 'macos_keychain' or has_secrets:
                        raise StudioError('原钥匙串主密钥不可用，请恢复本机钥匙串；不会创建新密钥覆盖现有凭据', 'vault_locked', 409)
                    key = Fernet.generate_key().decode()
                    keyring.set_password("director-studio-vault", str(db.root), key)
                self.mode = "macos_keychain"
            except StudioError:
                raise
            except Exception:
                if prior == 'macos_keychain' or has_secrets:
                    raise StudioError('无法访问原钥匙串，请解锁后重试；原凭据保持不变', 'vault_locked', 409)
                key = None
        if prior == 'macos_keychain' and key is None:
            raise StudioError('当前环境无法访问原钥匙串，未切换凭据存储方式', 'vault_locked', 409)
        if key is None:
            if path.exists():
                key = path.read_bytes()
            else:
                if prior == 'encrypted_file' or has_secrets:
                    raise StudioError('原凭据主密钥文件缺失，请恢复备份；未创建替代密钥', 'vault_key_missing', 409)
                key = Fernet.generate_key()
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as f:f.write(key)
                except FileExistsError:
                    key = path.read_bytes()
            os.chmod(path, 0o600)
        self.fernet = Fernet(key)
        with db.transaction() as c:
            c.execute("INSERT INTO meta VALUES('vault_mode',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (self.mode,))

    def put(self, connection_id: str, secret: str, c=None):
        if not secret.strip() or len(secret) > 16384:
            raise StudioError("凭据为空或格式异常")
        encrypted = self.fernet.encrypt(secret.strip().encode())
        if c is None:
            with self.db.transaction() as c:
                c.execute("INSERT INTO secrets(id,encrypted) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET encrypted=excluded.encrypted,version=version+1", (connection_id, encrypted))
        else:
            c.execute("INSERT INTO secrets(id,encrypted) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET encrypted=excluded.encrypted,version=version+1", (connection_id, encrypted))

    def get(self, connection_id: str) -> str:
        with self.db.connect() as c:
            row = c.execute("SELECT encrypted FROM secrets WHERE id=?", (connection_id,)).fetchone()
        if not row:
            raise StudioError("请先在配置页保存该服务的 API Key", "credentials_missing", 409)
        try:
            return self.fernet.decrypt(row[0]).decode()
        except Exception:
            raise StudioError("本机凭据无法解密，请重新配置", "credentials_invalid", 409)

    def version(self, connection_id: str, c=None) -> int:
        if c is None:
            with self.db.connect() as c:
                row = c.execute("SELECT version FROM secrets WHERE id=?", (connection_id,)).fetchone()
        else:
            row = c.execute("SELECT version FROM secrets WHERE id=?", (connection_id,)).fetchone()
        return row[0] if row else 0
