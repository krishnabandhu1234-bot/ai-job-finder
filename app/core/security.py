"""Local secret encryption.

Nothing sensitive (API keys, SMTP passwords, OAuth tokens) is ever stored in
plain text. We use a symmetric Fernet key that is generated once on first
run and persisted, with restrictive file permissions, outside of the
database and outside of the git-ignored .env file. This is appropriate for
a single-user local desktop app; it protects against casual disclosure
(e.g. someone reading the SQLite file directly or the DB file being
accidentally synced/shared) but is not a substitute for full-disk
encryption or an OS credential vault.

When the optional `keyring` package can access the Windows Credential
Locker, we prefer that instead of a key file. We fail closed: if neither
is available, encryption still works using the file-based key, so the app
never silently falls back to storing secrets unencrypted.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "AIJobFinder"
_KEYRING_USERNAME = "encryption-key"


class SecretBox:
    """Encrypts/decrypts short strings (API keys, passwords, tokens)."""

    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt a stored secret: key mismatch or corrupted data.")
            raise ValueError(
                "Could not decrypt stored secret. This usually means the encryption "
                "key changed or the data is corrupted. You may need to re-enter your "
                "credentials in Settings."
            )


def _load_key_from_keyring() -> bytes | None:
    try:
        import keyring
    except ImportError:
        return None
    try:
        value = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        return value.encode("utf-8") if value else None
    except Exception as exc:  # keyring backends can raise many different errors
        logger.warning("Keyring unavailable (%s); falling back to local key file.", exc)
        return None


def _store_key_in_keyring(key: bytes) -> bool:
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key.decode("utf-8"))
        return True
    except Exception as exc:
        logger.warning("Could not store encryption key in keyring (%s); using local key file.", exc)
        return False


def _write_key_file(key_path: Path, key: bytes) -> None:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    try:
        # Best-effort only: on Windows this merely toggles the read-only
        # attribute, not a real ACL restriction - %LOCALAPPDATA% is already
        # scoped to the current user by the OS. Kept for POSIX-style
        # environments (e.g. running the source tree under WSL for tests).
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def load_or_create_encryption_key(data_dir: Path, override_key: str | None = None) -> bytes:
    """Resolve the encryption key to use, in priority order:

    1. Explicit override (e.g. AIJF_ENCRYPTION_KEY env var) - for restoring
       a known key after reinstalling.
    2. The local key file under the app data directory, if one already
       exists there. This is deliberately checked *before* the OS keyring:
       the key file lives right next to the database it protects, so if a
       user restores/copies the whole data directory (backup, new machine,
       reinstall), the two travel together and stay consistent. The OS
       keyring does not travel with the data directory - trusting it first
       would let a stale or unrelated keyring entry silently shadow the
       correct, co-located key and permanently brick every secret already
       encrypted with it.
    3. The OS keyring (Windows Credential Locker), if available and no key
       file exists yet - and then back-filled to a key file so future
       restores of just the data directory are self-contained.
    4. A newly generated key, on first run, written to both the file and
       the keyring.
    """
    if override_key:
        return override_key.encode("utf-8")

    key_path = data_dir / "secret.key"
    if key_path.exists():
        key = key_path.read_bytes().strip()
        _store_key_in_keyring(key)  # keep the keyring in sync, best-effort
        return key

    from_keyring = _load_key_from_keyring()
    if from_keyring:
        _write_key_file(key_path, from_keyring)
        return from_keyring

    key = Fernet.generate_key()
    _write_key_file(key_path, key)
    _store_key_in_keyring(key)
    return key


def get_secret_box(data_dir: Path, override_key: str | None = None) -> SecretBox:
    key = load_or_create_encryption_key(data_dir, override_key)
    return SecretBox(key)
