"""Runtime configuration for the eBiblio MCP server.

Secrets are read from the environment only (never from files committed to the
repository).  See ``.env.example`` for the full list of variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://andalucia.ebiblio.es"
DEFAULT_DATA_DIR = "/data"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

#: Aliases so the same image can talk to any eBiblio deployment; the first
#: variable that is set wins.
_USERNAME_ALIASES = ("EBIBLIO_USERNAME", "ANDALUCIA_EBIBLIO_USERNAME")
_PASSWORD_ALIASES = ("EBIBLIO_PASSWORD", "ANDALUCIA_EBIBLIO_PASSWORD")


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or malformed."""


def _first_env(env: dict[str, str], names: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in names:
        value = env.get(name)
        if value:
            return name, value
    return None, None


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one server process."""

    base_url: str
    username: str
    password: str
    data_dir: Path
    timeout: float = 30.0
    user_agent: str = USER_AGENT
    libgourou_bin_dir: Path | None = None
    ebook_convert: str | None = None
    username_env: str = field(default="", compare=False)
    password_env: str = field(default="", compare=False)

    @property
    def adept_dir(self) -> Path:
        return self.data_dir / "adept"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ) if env is None else dict(env)
        username_env, username = _first_env(env, _USERNAME_ALIASES)
        password_env, password = _first_env(env, _PASSWORD_ALIASES)
        if not username:
            raise ConfigError(
                "missing credentials: set EBIBLIO_USERNAME (or ANDALUCIA_EBIBLIO_USERNAME)"
            )
        if not password:
            raise ConfigError(
                "missing credentials: set EBIBLIO_PASSWORD (or ANDALUCIA_EBIBLIO_PASSWORD)"
            )
        base_url = (env.get("EBIBLIO_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ConfigError("EBIBLIO_BASE_URL must be an absolute http(s) URL")
        bin_dir = env.get("EBIBLIO_LIBGOUROU_BIN_DIR")
        return cls(
            base_url=base_url,
            username=username,
            password=password,
            data_dir=Path(env.get("EBIBLIO_DATA_DIR") or DEFAULT_DATA_DIR),
            timeout=float(env.get("EBIBLIO_TIMEOUT") or 30.0),
            libgourou_bin_dir=Path(bin_dir) if bin_dir else None,
            ebook_convert=env.get("EBIBLIO_EBOOK_CONVERT") or None,
            username_env=username_env or "",
            password_env=password_env or "",
        )
