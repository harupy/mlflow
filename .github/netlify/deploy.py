"""Deploy a directory to Netlify using the file digest API.

References:
    - https://open-api.netlify.com/
    - https://github.com/netlify/cli/blob/13e973c22842b14013b854bb407cda70fd90733a/src/commands/deploy/deploy.ts
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal, TypedDict

API_BASE = "https://api.netlify.com/api/v1"


class DeployResponse(TypedDict, total=False):
    id: str
    site_id: str
    state: str
    url: str
    deploy_url: str
    deploy_ssl_url: str
    error_message: str | None
    required: list[str]
    title: str


POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 300
UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_RETRY_BASE_DELAY_SECONDS = 1
UPLOAD_MAX_WORKERS = min(os.cpu_count() or 4, 10)
REQUEST_TIMEOUT_SECONDS = 30


def _request(
    method: str,
    url: str,
    auth_token: str,
    body: Any = None,
    content_type: Literal["application/json", "application/octet-stream"] = "application/json",
) -> DeployResponse:
    headers = {"Authorization": f"Bearer {auth_token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode() if content_type == "application/json" else body
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        result: DeployResponse = json.loads(resp.read())
        return result


def _hash_files(deploy_dir: Path) -> dict[str, str]:
    files = {}
    for path in sorted(deploy_dir.rglob("*")):
        if path.is_file():
            hasher = hashlib.sha1(usedforsecurity=False)
            with path.open("rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            sha1 = hasher.hexdigest()
            rel = "/" + path.relative_to(deploy_dir).as_posix()
            files[rel] = sha1
    return files


def _create_deploy(
    site_id: str,
    auth_token: str,
    files: dict[str, str],
    message: str,
    alias: str,
) -> DeployResponse:
    url = f"{API_BASE}/sites/{site_id}/deploys"
    body: dict[str, Any] = {"files": files}
    if message:
        body["title"] = message
    if alias:
        body["branch"] = alias
    return _request("POST", url, auth_token, body)


def _upload_file(deploy_id: str, auth_token: str, file_path: str, content: bytes) -> DeployResponse:
    encoded_path = file_path.lstrip("/")
    url = f"{API_BASE}/deploys/{deploy_id}/files/{encoded_path}"
    for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
        try:
            return _request(
                "PUT", url, auth_token, body=content, content_type="application/octet-stream"
            )
        except urllib.error.URLError as e:
            if attempt == UPLOAD_MAX_ATTEMPTS:
                raise
            delay = UPLOAD_RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1)
            print(f"Failed to upload {file_path}: {e}, retrying in {delay}s...", file=sys.stderr)
            time.sleep(delay)

    raise AssertionError("unreachable")


def _wait_for_ready(deploy_id: str, auth_token: str) -> DeployResponse:
    url = f"{API_BASE}/deploys/{deploy_id}"
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        deploy = _request("GET", url, auth_token)
        state = deploy.get("state")
        if state == "ready":
            return deploy
        if state == "error":
            error_message = deploy.get("error_message", "unknown error")
            raise RuntimeError(f"Deploy failed: {error_message}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Deploy did not become ready within {POLL_TIMEOUT_SECONDS}s")


def deploy(
    site_id: str,
    auth_token: str,
    deploy_dir: str | Path,
    message: str = "",
    alias: str = "",
) -> DeployResponse:
    deploy_path = Path(deploy_dir).resolve()
    if not deploy_path.is_dir():
        raise FileNotFoundError(f"Deploy directory not found: {deploy_path}")

    # Hash all files
    files = _hash_files(deploy_path)
    print(f"Hashed {len(files)} files", file=sys.stderr)

    # Create deploy with file digest
    deploy_obj = _create_deploy(site_id, auth_token, files, message, alias)
    deploy_id = deploy_obj["id"]
    required = deploy_obj.get("required", [])
    print(f"Deploy {deploy_id} created, {len(required)} files to upload", file=sys.stderr)

    # Build sha1 -> path lookup for required files
    sha_to_paths: dict[str, list[str]] = {}
    for rel_path, sha1 in files.items():
        sha_to_paths.setdefault(sha1, []).append(rel_path)

    # Upload required files in parallel
    def _upload_one(sha1: str) -> str | None:
        paths = sha_to_paths.get(sha1, [])
        if not paths:
            return None
        rel_path = paths[0]
        content = (deploy_path / rel_path.lstrip("/")).read_bytes()
        _upload_file(deploy_id, auth_token, rel_path, content)
        return rel_path

    with concurrent.futures.ThreadPoolExecutor(max_workers=UPLOAD_MAX_WORKERS) as pool:
        futures = [pool.submit(_upload_one, sha1) for sha1 in required]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            if uploaded_path := future.result():
                print(f"Uploaded ({i}/{len(required)}): {uploaded_path}", file=sys.stderr)

    # Wait for deploy to be ready
    deploy_obj = _wait_for_ready(deploy_id, auth_token)
    print(f"Deploy ready: {deploy_obj.get('deploy_url', '')}", file=sys.stderr)
    return deploy_obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy a directory to Netlify")
    parser.add_argument("--dir", required=True, help="Directory to deploy")
    parser.add_argument("--message", default="", help="Deploy message")
    parser.add_argument("--alias", default="", help="Deploy alias for predictable URL")
    args = parser.parse_args()

    auth_token = os.environ.get("NETLIFY_AUTH_TOKEN")
    site_id = os.environ.get("NETLIFY_SITE_ID")
    if not auth_token or not site_id:
        print(
            "Error: NETLIFY_AUTH_TOKEN and NETLIFY_SITE_ID environment variables are required",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        result = deploy(site_id, auth_token, args.dir, args.message, args.alias)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if hasattr(e, "read"):
            print(e.read().decode(errors="replace"), file=sys.stderr)
        sys.exit(1)

    # Output JSON (matching netlify-cli --json output)
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
