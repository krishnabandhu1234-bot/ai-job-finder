"""Regression tests for the Phase 1 review finding: encryption key
resolution must prefer the local key file (co-located with the data it
protects) over the OS keyring, and must never crash on a corrupted secret.

The real OS keyring is never touched in tests - `_load_key_from_keyring`/
`_store_key_in_keyring` are monkeypatched so the suite stays hermetic.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.core import security


def test_generates_and_persists_a_new_key_on_first_run(tmp_path, monkeypatch):
    monkeypatch.setattr(security, "_load_key_from_keyring", lambda: None)
    stored = {}
    monkeypatch.setattr(security, "_store_key_in_keyring", lambda key: stored.setdefault("key", key) or True)

    key = security.load_or_create_encryption_key(tmp_path)

    assert (tmp_path / "secret.key").exists()
    assert (tmp_path / "secret.key").read_bytes().strip() == key
    assert stored["key"] == key


def test_existing_key_file_wins_over_a_different_keyring_entry(tmp_path, monkeypatch):
    file_key = Fernet.generate_key()
    (tmp_path / "secret.key").write_bytes(file_key)

    foreign_key = Fernet.generate_key()
    monkeypatch.setattr(security, "_load_key_from_keyring", lambda: foreign_key)
    monkeypatch.setattr(security, "_store_key_in_keyring", lambda key: True)

    resolved = security.load_or_create_encryption_key(tmp_path)

    assert resolved == file_key
    assert resolved != foreign_key


def test_keyring_key_is_used_and_backfilled_when_no_file_exists(tmp_path, monkeypatch):
    keyring_key = Fernet.generate_key()
    monkeypatch.setattr(security, "_load_key_from_keyring", lambda: keyring_key)
    monkeypatch.setattr(security, "_store_key_in_keyring", lambda key: True)

    resolved = security.load_or_create_encryption_key(tmp_path)

    assert resolved == keyring_key
    assert (tmp_path / "secret.key").read_bytes().strip() == keyring_key


def test_explicit_override_takes_precedence_over_everything(tmp_path, monkeypatch):
    (tmp_path / "secret.key").write_bytes(Fernet.generate_key())
    monkeypatch.setattr(security, "_load_key_from_keyring", lambda: Fernet.generate_key())

    override = Fernet.generate_key().decode("utf-8")
    resolved = security.load_or_create_encryption_key(tmp_path, override_key=override)

    assert resolved == override.encode("utf-8")


def test_secret_box_roundtrip():
    box = security.SecretBox(Fernet.generate_key())
    assert box.decrypt(box.encrypt("hello world")) == "hello world"
    assert box.decrypt(box.encrypt("")) == ""  # a legitimately empty secret still round-trips
    assert box.decrypt("") == ""  # empty ciphertext (e.g. never-set value) short-circuits


def test_secret_box_raises_a_friendly_error_on_corrupted_ciphertext():
    box = security.SecretBox(Fernet.generate_key())
    try:
        box.decrypt("not-a-valid-token")
        assert False, "expected ValueError"
    except ValueError:
        pass
