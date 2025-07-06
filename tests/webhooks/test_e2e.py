"""End-to-end tests for webhook functionality."""

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import pytest
import requests

import mlflow
from mlflow.entities.model_registry.webhook import WebhookEventType

SECRET = "test_webhook_secret"


@dataclass
class Server:
    url: str
    cwd: Path

    def wait_until_ready(self, health_route: str = "/health", max_attempts: int = 10) -> None:
        health_url: str = f"{self.url}{health_route}"
        for _ in range(max_attempts):
            try:
                resp: requests.Response = requests.get(health_url, timeout=2)
                if resp.status_code == 200:
                    return
            except requests.RequestException:
                time.sleep(1)
        raise RuntimeError(f"Failed to start server at {health_url}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _run_mlflow_server(tmp_path: Path) -> Generator[Server, None, None]:
    port = _free_port()
    backend_store_uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    log_file_path = tmp_path / "mlflow.log"

    with open(log_file_path, "w") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mlflow",
                "server",
                f"--port={port}",
                "--workers=1",
                f"--backend-store-uri={backend_store_uri}",
                f"--default-artifact-root=file://{tmp_path}/artifacts",
                "--dev",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=tmp_path,
            env=os.environ.copy() | {"MLFLOW_WEBHOOKS_ALLOWED_SCHEMES": "https,http"},
        )

        try:
            server = Server(url=f"http://localhost:{port}", cwd=tmp_path)
            server.wait_until_ready("/health")
            yield server
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@contextlib.contextmanager
def _run_webhook_app(tmp_path: Path) -> Generator[Server, None, None]:
    port = _free_port()
    log_file_path = tmp_path / "app.log"

    # Use the external webhook app file
    webhook_app_path: str = os.path.join(os.path.dirname(__file__), "webhook_app.py")

    with open(log_file_path, "w") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "fastapi",
                "run",
                webhook_app_path,
                "--port",
                str(port),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=tmp_path,
        )

        try:
            server = Server(url=f"http://localhost:{port}", cwd=tmp_path)
            server.wait_until_ready("/health")
            yield server
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.fixture(scope="session")
def mlflow_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[Server, None, None]:
    tmp_path = tmp_path_factory.mktemp("mlflow_server")
    with _run_mlflow_server(tmp_path) as server:
        yield server


@pytest.fixture(scope="session")
def webhook_app(tmp_path_factory: pytest.TempPathFactory) -> Generator[Server, None, None]:
    tmp_path = tmp_path_factory.mktemp("webhook_app")
    with _run_webhook_app(tmp_path) as server:
        yield server


@pytest.fixture
def mlflow_client(mlflow_server: Server) -> mlflow.MlflowClient:
    mlflow.set_tracking_uri(mlflow_server.url)
    mlflow.set_registry_uri(mlflow_server.url)
    return mlflow.MlflowClient(tracking_uri=mlflow_server.url, registry_uri=mlflow_server.url)


@pytest.fixture
def model_info() -> mlflow.models.model.ModelInfo:
    with mlflow.start_run():
        return mlflow.sklearn.log_model({"fake": "model"}, name="test_model")


def test_webhook_creation_and_listing(
    mlflow_client: mlflow.MlflowClient, webhook_app: Server
) -> None:
    assert len(mlflow_client.list_webhooks()) == 0

    mlflow_client.create_webhook(
        name="test-insecure",
        url=f"{webhook_app.url}/insecure-webhook",
        events=[WebhookEventType.REGISTERED_MODEL_CREATED.value],
        description="Test webhook without signature",
    )

    mlflow_client.create_webhook(
        name="test-secure",
        url=f"{webhook_app.url}/secure-webhook",
        events=[WebhookEventType.REGISTERED_MODEL_CREATED.value],
        description="Test webhook with HMAC signature",
        secret=SECRET,
    )

    webhooks: list = mlflow_client.list_webhooks()
    assert len(webhooks) == 2

    webhook_names: set[str] = {w.name for w in webhooks}
    assert "test-insecure" in webhook_names
    assert "test-secure" in webhook_names

    # Webhooks will be cleaned up when temporary sqlite is cleaned up


def test_webhook_events_dispatched(
    mlflow_client: mlflow.MlflowClient,
    webhook_app: Server,
    model_info: mlflow.models.model.ModelInfo,
) -> None:
    # Clear any existing logs
    log_file = webhook_app.cwd / "webhook_logs.jsonl"
    if log_file.exists():
        log_file.unlink()

    # Create webhooks for all event types
    mlflow_client.create_webhook(
        name="test-insecure",
        url=f"{webhook_app.url}/insecure-webhook",
        events=[e.value for e in WebhookEventType],
        description="Test webhook without signature",
    )

    mlflow_client.create_webhook(
        name="test-secure",
        url=f"{webhook_app.url}/secure-webhook",
        events=[e.value for e in WebhookEventType],
        description="Test webhook with HMAC signature",
        secret=SECRET,
    )

    # Trigger webhook events by performing model registry operations
    rm = mlflow_client.create_registered_model("test_registered_model")
    mv = mlflow_client.create_model_version(rm.name, model_info.model_uri)
    mlflow_client.set_model_version_tag(rm.name, mv.version, "test_tag", "test_value")
    mlflow_client.delete_model_version_tag(rm.name, mv.version, "test_tag")
    mlflow_client.set_registered_model_alias(rm.name, alias="test_alias", version=mv.version)
    mlflow_client.delete_registered_model_alias(rm.name, alias="test_alias")

    # Wait for webhooks to be delivered
    time.sleep(3)

    # Verify webhook logs
    assert log_file.exists(), "Webhook log file should exist after triggering events"
    webhook_logs = log_file.read_text().strip()
    log_lines = webhook_logs.splitlines() if webhook_logs else []

    # Should have received events for both webhooks
    # Each operation should trigger 2 webhooks (insecure + secure)
    expected_events = 6 * 2  # 6 operations x 2 webhooks
    assert len(log_lines) == expected_events, (
        f"Expected {expected_events} events, got {len(log_lines)}"
    )

    # Verify event structure
    for line in log_lines:
        event_data = json.loads(line)
        assert "endpoint" in event_data
        assert "payload" in event_data
        assert "headers" in event_data

        payload = event_data["payload"]
        assert "event_type" in payload
        assert "timestamp" in payload
        assert "delivery_id" in payload
        assert "data" in payload

        headers = event_data["headers"]
        assert "x-mlflow-event" in headers
        assert "x-mlflow-delivery" in headers
        assert "content-type" in headers

    # Verify secure webhook has signature
    secure_events = [
        json.loads(line) for line in log_lines if json.loads(line)["endpoint"] == "/secure-webhook"
    ]
    for event in secure_events:
        assert "x-mlflow-signature" in event["headers"]
        assert event["headers"]["x-mlflow-signature"].startswith("sha256=")


def test_webhook_delivery_id_uniqueness(
    mlflow_client: mlflow.MlflowClient, webhook_app: Server
) -> None:
    # Clear any existing logs
    log_file = webhook_app.cwd / "webhook_logs.jsonl"
    if log_file.exists():
        log_file.unlink()

    # Create webhook
    mlflow_client.create_webhook(
        name="test-delivery-id",
        url=f"{webhook_app.url}/insecure-webhook",
        events=[WebhookEventType.REGISTERED_MODEL_CREATED.value],
        description="Test webhook for delivery ID uniqueness",
    )

    # Trigger multiple events
    for i in range(3):
        mlflow_client.create_registered_model(f"test_model_{i}")

    # Wait for webhook deliveries
    time.sleep(2)

    # Verify delivery IDs are unique
    assert log_file.exists(), "Webhook log file should exist after triggering events"
    webhook_logs = log_file.read_text().strip()
    log_lines = webhook_logs.splitlines() if webhook_logs else []
    assert len(log_lines) >= 3, "Expected at least 3 webhook events"

    delivery_ids = set()
    for line in log_lines:
        event_data = json.loads(line)
        payload = event_data["payload"]
        delivery_id = payload["delivery_id"]
        header_delivery_id = event_data["headers"]["x-mlflow-delivery"]

        # Delivery ID should be in both payload and header
        assert delivery_id == header_delivery_id

        # Should be unique
        assert delivery_id not in delivery_ids, f"Duplicate delivery ID: {delivery_id}"
        delivery_ids.add(delivery_id)


def test_webhook_payload_structure(mlflow_client: mlflow.MlflowClient, webhook_app: Server) -> None:
    # Clear any existing logs
    log_file = webhook_app.cwd / "webhook_logs.jsonl"
    if log_file.exists():
        log_file.unlink()

    # Create webhook
    mlflow_client.create_webhook(
        name="test-payload",
        url=f"{webhook_app.url}/insecure-webhook",
        events=[WebhookEventType.REGISTERED_MODEL_CREATED.value],
        description="Test webhook payload structure",
    )

    # Trigger an event
    mlflow_client.create_registered_model("test_payload_model")

    # Wait for webhook delivery
    time.sleep(2)

    # Verify payload structure
    assert log_file.exists(), "Webhook log file should exist after triggering events"
    webhook_logs = log_file.read_text().strip()
    log_lines = webhook_logs.splitlines() if webhook_logs else []
    assert len(log_lines) >= 1, "Expected at least one webhook event"

    event_data = json.loads(log_lines[0])
    payload = event_data["payload"]

    # Verify required fields
    assert "event_type" in payload
    assert "timestamp" in payload
    assert "delivery_id" in payload
    assert "data" in payload

    # Verify event type
    assert payload["event_type"] == WebhookEventType.REGISTERED_MODEL_CREATED.value

    # Verify timestamp is recent
    timestamp_ms = payload["timestamp"]
    current_time_ms = int(time.time() * 1000)
    assert abs(current_time_ms - timestamp_ms) < 10000  # Within 10 seconds

    # Verify data contains model information
    data = payload["data"]
    assert "registered_model" in data
    assert data["registered_model"]["name"] == "test_payload_model"
