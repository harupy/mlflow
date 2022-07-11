import argparse
import requests


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-token", required=True)
    parser.add_argument("--render-owner-id", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--pr-number", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    url = "https://api.render.com/v1/services"
    payload = {
        "autoDeploy": "yes",
        "serviceDetails": {
            "publishPath": "mlflow/server/js/build",
            "pullRequestPreviewsEnabled": "no",
            "routes": [
                {"type": "redirect", "source": "/static-files/*", "destination": "/*"},
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
        "ownerId": args.owner_id,
        "type": "static_site",
        "name": f"mlflow-pr-{args.pr_number}",
        "repo": f"https://github.com/{args.repo}",
        "branch": args.branch,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {args.token}",
    }

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    print(response.text)


if __name__ == "__main__":
    main()
