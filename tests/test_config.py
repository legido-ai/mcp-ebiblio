"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest

from ebiblio_mcp.config import ConfigError, Settings


def test_defaults() -> None:
    settings = Settings.from_env(
        {"EBIBLIO_USERNAME": "u@example.com", "EBIBLIO_PASSWORD": "p"}
    )
    assert settings.base_url == "https://andalucia.ebiblio.es"
    assert settings.data_dir.as_posix() == "/data"
    assert settings.adept_dir.as_posix() == "/data/adept"
    assert settings.username_env == "EBIBLIO_USERNAME"


def test_platform_specific_aliases() -> None:
    settings = Settings.from_env(
        {"ANDALUCIA_EBIBLIO_USERNAME": "u@example.com", "ANDALUCIA_EBIBLIO_PASSWORD": "p"}
    )
    assert settings.username == "u@example.com"
    assert settings.password_env == "ANDALUCIA_EBIBLIO_PASSWORD"


def test_generic_name_wins_over_alias() -> None:
    settings = Settings.from_env(
        {
            "EBIBLIO_USERNAME": "generic@example.com",
            "ANDALUCIA_EBIBLIO_USERNAME": "alias@example.com",
            "EBIBLIO_PASSWORD": "p",
        }
    )
    assert settings.username == "generic@example.com"


def test_missing_username() -> None:
    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env({"EBIBLIO_PASSWORD": "p"})
    assert "EBIBLIO_USERNAME" in str(excinfo.value)


def test_missing_password() -> None:
    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env({"EBIBLIO_USERNAME": "u"})
    assert "EBIBLIO_PASSWORD" in str(excinfo.value)


def test_invalid_base_url() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(
            {"EBIBLIO_USERNAME": "u", "EBIBLIO_PASSWORD": "p", "EBIBLIO_BASE_URL": "ebiblio.es"}
        )


def test_data_dir_and_tool_overrides() -> None:
    settings = Settings.from_env(
        {
            "EBIBLIO_USERNAME": "u",
            "EBIBLIO_PASSWORD": "p",
            "EBIBLIO_DATA_DIR": "/srv/ebiblio",
            "EBIBLIO_LIBGOUROU_BIN_DIR": "/opt/libgourou",
            "EBIBLIO_EBOOK_CONVERT": "/usr/bin/ebook-convert",
        }
    )
    assert settings.downloads_dir.as_posix() == "/srv/ebiblio/downloads"
    assert settings.libgourou_bin_dir.as_posix() == "/opt/libgourou"
    assert settings.ebook_convert == "/usr/bin/ebook-convert"
