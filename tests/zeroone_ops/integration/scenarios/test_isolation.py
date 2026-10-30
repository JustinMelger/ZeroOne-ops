"""Verify accidental network and developer-environment access fail closed."""

import os
import socket

import pytest

from zeroone_ops.settings import load_openai_connection_config


def test_parent_network_connections_are_rejected() -> None:
    with socket.socket() as connection:
        with pytest.raises(pytest.fail.Exception, match="network connection"):
            connection.connect(("127.0.0.1", 443))
    with pytest.raises(pytest.fail.Exception, match="network connection"):
        socket.create_connection(("127.0.0.1", 443))
    with pytest.raises(pytest.fail.Exception, match="network connection"):
        socket.getaddrinfo("provider.invalid", 443)


def test_environment_files_and_credential_inheritance_are_rejected() -> None:
    assert not any(
        name.startswith(("OPENAI_", "GITHUB_", "GITLAB_", "AWS_", "DATABRICKS_"))
        for name in os.environ
    )
    assert os.environ["GIT_ALLOW_PROTOCOL"] == "file"
    assert os.environ["ZEROONE_MLFLOW_ENABLED"] == "false"
    with pytest.raises(pytest.fail.Exception, match="load a .env file"):
        load_openai_connection_config()
