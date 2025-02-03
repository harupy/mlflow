# /// script
# requires-python = "==3.10"
# dependencies = [
#   "requests",
# ]
# ///
# ruff: noqa: T201
import os
import subprocess
import sys
import uuid

import requests


def main():
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    MLFLOW_3_BRANCH_NAME = "mlflow-3"
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not found in environment variables", file=sys.stderr)
        sys.exit(1)

    TITLE = "Sync with master"

    # Exit if there is already a PR with the same title
    owner = "mlflow"
    repo = "mlflow"
    prs = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        params={
            "state": "open",
            "base": MLFLOW_3_BRANCH_NAME,
            "title": TITLE,
        },
    )
    prs.raise_for_status()
    prs_data = prs.json()
    if prs_data:
        url = prs[0]["html_url"]
        print(f"PR already exists: {url}")
        sys.exit(0)

    # Fetch master and mlflow-3 branches
    subprocess.check_call(["git", "fetch", "origin", "master"])
    subprocess.check_call(["git", "fetch", "origin", MLFLOW_3_BRANCH_NAME])

    # Sync master into mlflow-3
    branch_name = f"sync-{uuid.uuid4()}"
    subprocess.check_call(["git", "checkout", "-b", branch_name, f"origin/{MLFLOW_3_BRANCH_NAME}"])
    prc = subprocess.run(["git", "merge", "origin/master"])
    if prc.returncode != 0:
        print("Merge failed (possibly due to conflicts). Aborting.", file=sys.stderr)
        sys.exit(1)

    # Create a pull request
    subprocess.check_call(["git", "push", "origin", branch_name])
    # pr = requests.post(
    #     f"https://api.github.com/repos/{owner}/{repo}/pulls",
    #     headers={"Authorization": f"token {GITHUB_TOKEN}"},
    #     json={
    #         "title": TITLE,
    #         "head": branch_name,
    #         "base": MLFLOW_3_BRANCH_NAME,
    #         "body": "This PR was created automatically by the sync workflow.",
    #     },
    # )
    # pr.raise_for_status()
    # print(pr.json()["html_url"])


if __name__ == "__main__":
    main()
