"""Remembered account profiles; existing AuthManager remains the credential owner."""
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from .auth import AuthManager


class AccountStore:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "accounts.json"
        self._accounts = {}
        self._active = ""
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("accounts"), dict):
                    self._accounts = {key: label for key, label in data["accounts"].items()
                                      if self._valid_id(key) and isinstance(label, str) and label.strip()}
                    active = data.get("active", "")
                    self._active = active if isinstance(active, str) else ""
            except (OSError, ValueError, TypeError):
                pass
        # The original single-account session stays at the old location.
        if AuthManager(self.root).has_saved_session:
            self._accounts.setdefault("default", "原账号")
        self._accounts = {key: label for key, label in self._accounts.items()
                          if self.auth_for(key).has_saved_session}
        if self._active not in self._accounts:
            self._active = next(iter(self._accounts), "")

    @staticmethod
    def _valid_id(account_id):
        return account_id == "default" or (isinstance(account_id, str) and len(account_id) == 32
                                           and all(char in "0123456789abcdef" for char in account_id))

    @property
    def active_id(self):
        return self._active

    def items(self):
        return list(self._accounts.items())

    def label(self, account_id):
        return self._accounts.get(account_id, "")

    def auth_for(self, account_id):
        if not self._valid_id(account_id):
            raise ValueError("Invalid account ID")
        return AuthManager(self.root if account_id == "default" else self.root / "profiles" / account_id)

    def new_id(self):
        return uuid4().hex

    def register(self, account_id, label):
        if not self.auth_for(account_id).has_saved_session:
            return False
        label = label.strip() or "未命名账号"
        if self._accounts.get(account_id) == label and self._active == account_id:
            return True
        self._save({**self._accounts, account_id: label}, account_id)
        return True

    def activate(self, account_id):
        if account_id not in self._accounts:
            raise KeyError(account_id)
        self._save(self._accounts, account_id)

    def forget(self, account_id):
        accounts = dict(self._accounts)
        accounts.pop(account_id, None)
        active = next(iter(accounts), "") if self._active == account_id else self._active
        self._save(accounts, active)

    def _save(self, accounts, active):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".accounts-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "active": active, "accounts": accounts},
                          stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            # Commit memory only after the index is safely on disk. In particular,
            # a failed register must remain retryable instead of looking saved.
            self._accounts, self._active = accounts, active
        finally:
            if os.path.exists(name):
                os.unlink(name)
