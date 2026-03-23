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


def test_default_credentials_warning_logged(monkeypatch):
    monkeypatch.setenv("MLFLOW_FLASK_SERVER_SECRET_KEY", "test-secret")

    with (
        mock.patch("mlflow.server.auth.store.init_db") as mock_init_db,
        mock.patch("mlflow.server.auth.create_admin_user") as mock_create_admin,
        mock.patch("mlflow.server.auth.auth_config", read_auth_config()),
        mock.patch("mlflow.server.auth._logger") as mock_logger,
    ):
        create_app(Flask(__name__))
        mock_init_db.assert_called_once()
        mock_create_admin.assert_called_once_with(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if "default credentials" in str(call)
    ]
    assert len(warning_calls) == 1


def test_no_warning_when_credentials_customized(monkeypatch):
    monkeypatch.setenv("MLFLOW_FLASK_SERVER_SECRET_KEY", "test-secret")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")

    with (
        mock.patch("mlflow.server.auth.store.init_db") as mock_init_db,
        mock.patch("mlflow.server.auth.create_admin_user") as mock_create_admin,
        mock.patch("mlflow.server.auth.store.has_user", return_value=False) as mock_has_user,
        mock.patch("mlflow.server.auth.auth_config", read_auth_config()),
        mock.patch("mlflow.server.auth._logger") as mock_logger,
    ):
        create_app(Flask(__name__))
        mock_init_db.assert_called_once()
        mock_create_admin.assert_called_once_with("custom-admin", "custom-password")
        mock_has_user.assert_called_once_with(DEFAULT_ADMIN_USERNAME)

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if "default credentials" in str(call)
    ]
    assert len(warning_calls) == 0


def test_stale_default_admin_warning(monkeypatch):
    monkeypatch.setenv("MLFLOW_FLASK_SERVER_SECRET_KEY", "test-secret")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")

    with (
        mock.patch("mlflow.server.auth.store.init_db") as mock_init_db,
        mock.patch("mlflow.server.auth.create_admin_user") as mock_create_admin,
        mock.patch("mlflow.server.auth.store.has_user", return_value=True) as mock_has_user,
        mock.patch("mlflow.server.auth.auth_config", read_auth_config()),
        mock.patch("mlflow.server.auth._logger") as mock_logger,
    ):
        create_app(Flask(__name__))
        mock_init_db.assert_called_once()
        mock_create_admin.assert_called_once_with("custom-admin", "custom-password")
        mock_has_user.assert_called_once_with(DEFAULT_ADMIN_USERNAME)

    warning_calls = [
        call for call in mock_logger.warning.call_args_list if "still exists" in str(call)
    ]
    assert len(warning_calls) == 1
