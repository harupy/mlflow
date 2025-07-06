"""Test webhook receiver app for MLflow webhook testing."""

import hashlib
import hmac
import json
from pathlib import Path

import fastapi
from fastapi import HTTPException, Request

# Secret for HMAC signature verification
SECRET = "test_webhook_secret"

# Create FastAPI app
app = fastapi.FastAPI()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/insecure-webhook")
async def insecure_webhook(request: Request):
    """Webhook endpoint without signature verification."""
    webhook_data = {
        "endpoint": "/insecure-webhook",
        "payload": await request.json(),
        "headers": dict(request.headers),
    }

    # Log to file
    log_file = Path("webhook_logs.jsonl")
    with log_file.open("ab") as f:
        f.write(json.dumps(webhook_data).encode("utf-8") + b"\n")

    return {"status": "received"}


@app.post("/secure-webhook")
async def secure_webhook(request: Request):
    """Webhook endpoint with HMAC signature verification."""
    request_body = await request.body()
    signature_header = request.headers.get("x-mlflow-signature", "")

    # Verify signature format
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=400, detail="Invalid signature format")

    # Verify HMAC signature
    received_signature = signature_header[7:]  # Remove "sha256=" prefix
    expected_signature = hmac.new(SECRET.encode(), request_body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(received_signature, expected_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Log verified webhook
    webhook_data = {
        "endpoint": "/secure-webhook",
        "payload": await request.json(),
        "headers": dict(request.headers),
    }

    log_file = Path("webhook_logs.jsonl")
    with log_file.open("ab") as f:
        f.write(json.dumps(webhook_data).encode("utf-8") + b"\n")

    return {"status": "received"}


@app.post("/failing-webhook")
async def failing_webhook(request: Request):
    """Webhook endpoint that always fails (for testing error handling)."""
    raise HTTPException(status_code=500, detail="Webhook intentionally failed")


@app.delete("/logs")
async def clear_logs():
    """Clear webhook logs."""
    log_file = Path("webhook_logs.jsonl")
    if log_file.exists():
        log_file.unlink()
    return {"status": "logs cleared"}


@app.get("/logs")
async def get_logs():
    """Get webhook logs."""
    log_file = Path("webhook_logs.jsonl")
    if not log_file.exists():
        return {"logs": []}

    logs = []
    with log_file.open("r") as f:
        for line in f:
            if line.strip():
                logs.append(json.loads(line.strip()))

    return {"logs": logs}


# For running directly
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
