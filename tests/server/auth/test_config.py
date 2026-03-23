from unittest import mock

import pytest
from flask import Flask

from mlflow.server.auth import create_app
from mlflow.server.auth.config import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    read_auth_config,
)

pytestmark = pytest.mark.notrackingurimock


def test_read_auth_config_defaults():
    config = read_auth_config()
    assert config.admin_username == DEFAULT_ADMIN_USERNAME
    assert config.admin_password == DEFAULT_ADMIN_PASSWORD


def test_env_var_overrides_admin_username(monkeypatch):
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    config = read_auth_config()
    assert config.admin_username == "custom-admin"
    assert config.admin_password == DEFAULT_ADMIN_PASSWORD


def test_env_var_overrides_admin_password(monkeypatch):
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")
    config = read_auth_config()
    assert config.admin_username == DEFAULT_ADMIN_USERNAME
    assert config.admin_password == "custom-password"


def test_env_var_overrides_both(monkeypatch):
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")
    config = read_auth_config()
    assert config.admin_username == "custom-admin"
    assert config.admin_password == "custom-password"


@pytest.fixture
def _mock_auth_app(monkeypatch):
    monkeypatch.setenv("MLFLOW_FLASK_SERVER_SECRET_KEY", "test-secret")
    monkeypatch.setattr(
        "mlflow.server.auth.store.init_db",
        lambda uri: None,
    )
    monkeypatch.setattr(
        "mlflow.server.auth.create_admin_user",
        lambda username, password: None,
    )


@pytest.mark.usefixtures("_mock_auth_app")
def test_default_credentials_warning_logged(monkeypatch):
    monkeypatch.setattr("mlflow.server.auth.auth_config", read_auth_config())

    with mock.patch("mlflow.server.auth._logger") as mock_logger:
        create_app(Flask(__name__))

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if "default credentials" in str(call)
    ]
    assert len(warning_calls) == 1


@pytest.mark.usefixtures("_mock_auth_app")
def test_no_warning_when_credentials_customized(monkeypatch):
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")
    monkeypatch.setattr("mlflow.server.auth.auth_config", read_auth_config())
    monkeypatch.setattr("mlflow.server.auth.store.has_user", lambda username: False)

    with mock.patch("mlflow.server.auth._logger") as mock_logger:
        create_app(Flask(__name__))

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if "default credentials" in str(call)
    ]
    assert len(warning_calls) == 0


@pytest.mark.usefixtures("_mock_auth_app")
def test_stale_default_admin_warning(monkeypatch):
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")
    monkeypatch.setattr("mlflow.server.auth.auth_config", read_auth_config())
    monkeypatch.setattr("mlflow.server.auth.store.has_user", lambda username: True)

    with mock.patch("mlflow.server.auth._logger") as mock_logger:
        create_app(Flask(__name__))

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if "still exists" in str(call)
    ]
    assert len(warning_calls) == 1
