from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.constants import LLMProvider
from app.core.config import AppConfig, reload_config_for_tests


def test_defaults_are_demo_friendly(app_config):
    assert app_config.demo_mode is True
    assert app_config.llm_provider == LLMProvider.NONE
    assert app_config.has_llm_configured() is False


def test_data_dir_override_is_used(app_config, tmp_path):
    assert app_config.data_dir == tmp_path
    assert app_config.database_path == tmp_path / "aijobfinder.db"


def test_directories_are_created(app_config):
    assert app_config.data_dir.exists()
    assert app_config.resumes_dir.exists()
    assert app_config.logs_dir.exists()


def test_invalid_log_level_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("AIJF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIJF_LOG_LEVEL", "NOT_A_LEVEL")
    with pytest.raises(ValidationError):
        reload_config_for_tests()
    monkeypatch.setenv("AIJF_LOG_LEVEL", "INFO")
    reload_config_for_tests()


def test_has_llm_configured_requires_key_for_hosted_providers(monkeypatch, tmp_path):
    monkeypatch.setenv("AIJF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIJF_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = reload_config_for_tests()
    assert cfg.has_llm_configured() is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    cfg = reload_config_for_tests()
    assert cfg.has_llm_configured() is True
