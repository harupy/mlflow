import contextlib
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import fastapi
import requests
from fastapi import Request

import mlflow
from mlflow.entities.model_registry.webhook import WebhookEventType

app = fastapi.FastAPI()


@app.get("/health")
async def health_check():
    return {"status": "ok"}


SECRET = "test_webhook_secret"


@app.post("/insecure-webhook")
async def insecure_webhook(request: Request):
    with open("logs.jsonl", "ab") as f:
        webhook_data = {
            "endpoint": "/insecure-webhook",
            "payload": await request.json(),
            "headers": dict(request.headers),
        }
        f.write(json.dumps(webhook_data).encode("utf-8") + b"\n")

    return {"status": "received"}


def verify_signature(request_body: bytes, signature_header: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False

    received_signature = signature_header[7:]  # Remove "sha256=" prefix
    expected_signature = hmac.new(SECRET.encode(), request_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_signature, expected_signature)


@app.post("/secure-webhook")
async def secure_webhook(request: Request):
    with open("logs.jsonl", "ab") as f:
        webhook_data = {
            "endpoint": "/secure-webhook",
            "payload": await request.json(),
            "headers": dict(request.headers),
        }
        assert verify_signature(await request.body(), request.headers.get("x-mlflow-signature", ""))

        f.write(json.dumps(webhook_data).encode("utf-8") + b"\n")

    return {"status": "received"}


def safe_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@dataclass
class Server:
    url: str
    cwd: Path


def wait_until_ready(health: str, max_attempts: int = 10) -> None:
    for _ in range(max_attempts):
        try:
            resp = requests.get(health)
            if resp.status_code == 200:
                break
        except requests.ConnectionError:
            time.sleep(1)
    else:
        raise RuntimeError(f"Failed to start FastAPI app at {health}")


@contextlib.contextmanager
def run_mlflow_server() -> Generator[Server, None, None]:
    port = safe_port()
    with tempfile.TemporaryDirectory() as temp_dir:
        backend_store_uri = f"sqlite:///{os.path.join(temp_dir, 'mlflow.db')}"
        log_file = os.path.join(temp_dir, "mlflow.log")
        print("mlflow server log file:", log_file)
        with open(log_file, "w") as log_file:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "mlflow",
                    "server",
                    f"--port={port}",
                    "--workers=1",
                    f"--backend-store-uri={backend_store_uri}",
                    f"--default-artifact-root=file://{temp_dir}/artifacts",
                    "--dev",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=temp_dir,
                env=os.environ.copy() | {"MLFLOW_WEBHOOKS_ALLOWED_SCHEMES": "https,http"},
            )
            try:
                wait_until_ready(f"http://localhost:{port}/health")
                return Server(url=f"http://localhost:{port}", cwd=Path(temp_dir))
            finally:
                process.terminate()
                process.wait(timeout=10)
                subprocess.check_call(["pkill", "-f", "gunicorn"])  # Ensure no lingering processes


@contextlib.contextmanager
def run_app() -> Generator[Server, None, None]:
    port = safe_port()
    with tempfile.TemporaryDirectory() as temp_dir:
        log_file = os.path.join(temp_dir, "app.log")
        print("App log file:", log_file)
        with open(log_file, "w") as log_file:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "fastapi",
                    "run",
                    __file__,
                    "--port",
                    str(port),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=temp_dir,
            )
            try:
                wait_until_ready(f"http://localhost:{port}/health")
                yield Server(url=f"http://localhost:{port}", cwd=Path(temp_dir))
            finally:
                process.terminate()
                process.wait(timeout=10)


def main():
    with run_mlflow_server() as mlflow_server, run_app() as app_server:
        mlflow.set_tracking_uri(mlflow_server.url)
        mlflow.set_registry_uri(mlflow_server.url)
        client = mlflow.MlflowClient(tracking_uri=mlflow_server.url, registry_uri=mlflow_server.url)
        with mlflow.start_run():
            model_info = mlflow.sklearn.log_model({"fake": "model"}, name="model")

        assert len(client.list_webhooks()) == 0

        # Create webhook WITHOUT secret (for non-secure endpoint)
        webhook_no_secret = client.create_webhook(
            name="insecure-webhook",
            url=f"{app_server.url}/insecure-webhook",
            events=[v.value for v in WebhookEventType],
            description="Test webhook without signature",
        )
        print("\nCreated webhook without secret:")
        print(webhook_no_secret)

        # Create webhook WITH secret (for secure endpoint)
        webhook_with_secret = client.create_webhook(
            name="secure-webhook",
            url=f"{app_server.url}/secure-webhook",
            events=[v.value for v in WebhookEventType],
            description="Test webhook with HMAC signature",
            secret=SECRET,
        )
        print("\nCreated webhook with secret:")
        print(webhook_with_secret)

        assert len(client.list_webhooks()) == 2
        # Registered models
        rm = client.create_registered_model("test_registered_model")
        # Model versions
        mv = client.create_model_version(rm.name, model_info.model_uri)
        client.set_model_version_tag(rm.name, mv.version, "test_tag", "test_value")
        client.delete_model_version_tag(rm.name, mv.version, "test_tag")
        # Model aliases
        client.set_registered_model_alias(rm.name, alias="test_alias", version=mv.version)
        client.delete_registered_model_alias(rm.name, alias="test_alias")

        time.sleep(3)

        # Read and analyze webhook responses
        app_logs = app_server.cwd / "logs.jsonl"
        webhook_logs = app_logs.read_text().strip()
        print("\nWebhook logs:")
        print(webhook_logs)

        assert (len(webhook_logs.splitlines())) == 6 * 2

        # Clean up webhooks
        client.delete_webhook(webhook_no_secret.id)
        client.delete_webhook(webhook_with_secret.id)


if __name__ == "__main__":
    main()
