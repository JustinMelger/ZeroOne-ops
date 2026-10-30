"""Isolate scenario processes from developer credentials, plugins, and networking."""

import os
import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_scenario_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow local Git transport but fail unexpected parent-process networking."""
    process_environment = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
    }
    for name in tuple(os.environ):
        if name.upper() not in process_environment:
            monkeypatch.delenv(name, raising=False)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("ZEROONE_MLFLOW_ENABLED", "false")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.chdir(tmp_path)

    def reject_network(*args: object, **kwargs: object) -> None:
        pytest.fail("Offline scenario attempted a network connection", pytrace=False)

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)

    def reject_environment_file() -> None:
        pytest.fail("Offline scenario attempted to load a .env file", pytrace=False)

    monkeypatch.setattr("zeroone_ops.settings._load_environment_file", reject_environment_file)
