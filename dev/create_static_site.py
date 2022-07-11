from pprint import pprint
import argparse
import requests
import os
import time


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-token", required=True)
    parser.add_argument("--render-owner-id", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--pr-number", required=True)
    parser.add_argument("--commit-sha", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    sess = requests.Session()
    sess.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {args.render_token}",
        }
    )
    service_name = f"mlflow-pr-{args.pr_number}"
    url = "https://api.render.com/v1/services"

    # List services
    response = sess.get(
        url,
        params={
            "limit": 100,
            "name": service_name,
        },
    )
    response.raise_for_status()
    services = response.json()
    pprint(services)

    if len(services) == 0:
        # Create a new service
        payload = {
            "autoDeploy": "yes",
            "serviceDetails": {
                "publishPath": "mlflow/server/js/build",
                "pullRequestPreviewsEnabled": "no",
                "routes": [
                    {
                        "type": "redirect",
                        "source": "/static-files/*",
                        "destination": "/*",
                    },
                    {
                        "type": "rewrite",
                        "source": "/ajax-api/*",
                        "destination": "https://mlflow.onrender.com/ajax-api/*",
                    },
                    {
                        "type": "rewrite",
                        "source": "/get-artifact",
                        "destination": "https://mlflow.onrender.com/get-artifact",
                    },
                ],
                "buildCommand": "cd mlflow/server/js && yarn install && yarn build",
            },
            "ownerId": args.render_owner_id,
            "type": "static_site",
            "name": f"mlflow-pr-{args.pr_number}",
            "repo": f"https://github.com/{args.repo}",
            "branch": args.branch,
        }
        response = sess.post(url, json=payload)
        response.raise_for_status()
        resp_data = response.json()
        pprint(resp_data)
    else:
        # Update the service
        service = services[0]
        service_id = service["service"]["id"]
        payload = {"branch": args.branch}
        response = sess.patch(f"{url}/{service_id}", json=payload)
        response.raise_for_status()
        resp_data = response.json()
        pprint(resp_data)

    # Wait for the service to be ready
    start_time = time.time()
    one_minute = 60
    max_wait_time_in_sec = 30 * one_minute
    while time.time() - start_time < max_wait_time_in_sec:
        time.sleep(one_minute)
        response = sess.get(f"{url}/{service_id}/deploys")
        response.raise_for_status()
        deploys = response.json()
        if len(deploys) == 0:
            continue
        latest_deploy = deploys[0]["deploy"]
        print(
            "Deploy {id} is {status}".format(id=latest_deploy["id"], status=latest_deploy["status"])
        )
        if latest_deploy["status"] == "live":
            break

    # Post the service URL as a comment on the PR
    service_url = resp_data["serviceDetails"]["url"]
    github_token = os.environ["GITHUB_TOKEN"]
    sess = requests.Session()
    sess.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {github_token}",
        }
    )
    payload = {"body": f"UI preview is available at {service_url} (commit: {args.commit_sha})"}
    response = sess.post(
        f"https://api.github.com/repos/{args.repo}/issues/{args.pr_number}/comments", json=payload
    )
    response.raise_for_status()
    resp_data = response.json()
    pprint(resp_data)


if __name__ == "__main__":
    main()
