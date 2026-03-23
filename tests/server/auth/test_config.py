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


def _create_app_and_get_warnings(monkeypatch, tmp_sqlite_uri):
    """Start a real auth app with a temp DB and capture warning log calls."""
    monkeypatch.setenv("MLFLOW_FLASK_SERVER_SECRET_KEY", "test-secret")
    config = read_auth_config()._replace(database_uri=tmp_sqlite_uri)

    # _logger.propagate is False, so caplog can't capture — mock only the logger
    with (
        mock.patch("mlflow.server.auth.auth_config", config),
        mock.patch("mlflow.server.auth._logger") as mock_logger,
    ):
        create_app(Flask(__name__))

    return mock_logger.warning.call_args_list


def test_default_credentials_warning_logged(monkeypatch, tmp_sqlite_uri):
    warnings = _create_app_and_get_warnings(monkeypatch, tmp_sqlite_uri)
    assert any("default credentials" in str(call) for call in warnings)


def test_no_warning_when_credentials_customized(monkeypatch, tmp_sqlite_uri):
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")

    warnings = _create_app_and_get_warnings(monkeypatch, tmp_sqlite_uri)
    assert not any("default credentials" in str(call) for call in warnings)
    assert not any("still exists" in str(call) for call in warnings)


def test_stale_default_admin_warning(monkeypatch, tmp_sqlite_uri):
    # First, create the default admin user in the DB
    from mlflow.server.auth import store

    store.init_db(tmp_sqlite_uri)
    store.create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, is_admin=True)

    # Now start the app with a custom admin username — the old "admin" is still in the DB
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_USERNAME", "custom-admin")
    monkeypatch.setenv("MLFLOW_AUTH_ADMIN_PASSWORD", "custom-password")

    warnings = _create_app_and_get_warnings(monkeypatch, tmp_sqlite_uri)
    assert any("still exists" in str(call) for call in warnings)
