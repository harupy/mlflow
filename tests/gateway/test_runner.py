import subprocess
import sys
import time
import requests
from pathlib import Path
from typing import Any
import yaml

from tests.helper_functions import get_safe_port

import pytest
from mlflow.gateway.utils import kill_child_processes


class Gateway:
    def __init__(self, config_path: str, *args, **kwargs):
        self.port = get_safe_port()
        self.host = "localhost"
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mlflow",
                "gateway",
                "start",
                "--config-path",
                config_path,
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--workers",
                "2",
            ],
            *args,
            **kwargs,
        )
        self.wait_until_ready()

    def wait_until_ready(self) -> None:
        s = time.time()
        while time.time() - s < 10:
            try:
                if self.get("health").ok:
                    return
            except requests.exceptions.ConnectionError:
                time.sleep(0.5)

        raise Exception("Gateway failed to start")

    def request(self, method: str, path: str, *args: Any, **kwargs: Any) -> requests.Response:
        return requests.request(method, f"http://{self.host}:{self.port}/{path}", *args, **kwargs)

    def get(self, path: str, *args: Any, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, *args, **kwargs)

    def assert_health(self):
        assert self.get("health").ok

    def post(self, path: str, *args: Any, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, *args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        kill_child_processes(self.process.pid)
        self.process.terminate()
        self.process.wait()


@pytest.fixture
def basic_config_dict():
    return {
        "routes": [
            {
                "name": "completions-gpt4",
                "type": "llm/v1/completions",
                "model": {
                    "name": "gpt-4",
                    "provider": "openai",
                    "config": {
                        "openai_api_key": "mykey",
                        "openai_api_base": "https://api.openai.com/v1",
                        "openai_api_version": "2023-05-15",
                        "openai_api_type": "open_ai",
                    },
                },
            },
            {
                "name": "claude-chat",
                "type": "llm/v1/chat",
                "model": {
                    "name": "claude-v1",
                    "provider": "anthropic",
                    "config": {
                        "anthropic_api_key": "claudekey",
                    },
                },
            },
        ]
    }


@pytest.fixture
def basic_routes():
    return {
        "routes": [
            {
                "name": "completions-gpt4",
                "type": "llm/v1/completions",
                "model": {"name": "gpt-4", "provider": "openai"},
            },
            {
                "name": "claude-chat",
                "type": "llm/v1/chat",
                "model": {"name": "claude-v1", "provider": "anthropic"},
            },
        ]
    }


@pytest.fixture
def update_config_dict():
    return {
        "routes": [
            {
                "name": "claude-completions",
                "type": "llm/v1/completions",
                "model": {
                    "name": "claude-v1",
                    "provider": "anthropic",
                    "config": {
                        "anthropic_api_key": "MY_ANTHROPIC_KEY",
                    },
                },
            },
        ]
    }


@pytest.fixture
def update_routes():
    return {
        "routes": [
            {
                "model": {"name": "claude-v1", "provider": "anthropic"},
                "name": "claude-completions",
                "type": "llm/v1/completions",
            }
        ]
    }


@pytest.fixture
def invalid_config_dict():
    return {
        "routes": [
            {
                "invalid_name": "invalid",
                "type": "llm/v1/chat",
                "model": {"invalidkey": "invalid", "invalid_provider": "invalid"},
            }
        ]
    }


def store_conf(path, name, conf):
    conf_path = path.joinpath(name)
    conf_path.write_text(yaml.safe_dump(conf))
    return conf_path


def wait():
    """
    A sleep statement for testing purposes only to ensure that the file watch and app reload
    has enough time to resolve to updated endpoints.
    """
    time.sleep(2)


def test_server_update(
    tmp_path: Path, basic_config_dict, update_config_dict, basic_routes, update_routes
):
    config = str(store_conf(tmp_path, "config.yaml", basic_config_dict))

    with Gateway(config) as gateway:
        response = gateway.get("gateway/routes/")
        assert response.json() == basic_routes

        # push an update to the config file
        store_conf(tmp_path, "config.yaml", update_config_dict)

        # Ensure there is no server downtime
        gateway.assert_health()

        # Wait for the app to restart
        wait()
        response = gateway.get("gateway/routes/")

        assert response.json() == update_routes

        # push the original file back
        store_conf(tmp_path, "config.yaml", basic_config_dict)
        gateway.assert_health()
        wait()
        response = gateway.get("gateway/routes/")
        assert response.json() == basic_routes


def test_server_update_with_invalid_config(
    tmp_path: Path, basic_config_dict, invalid_config_dict, basic_routes
):
    config = str(store_conf(tmp_path, "config.yaml", basic_config_dict))

    with Gateway(config) as gateway:
        response = gateway.get("gateway/routes/")
        assert response.json() == basic_routes
        # Give filewatch a moment to cycle
        wait()
        # push an invalid config
        store_conf(tmp_path, "config.yaml", invalid_config_dict)
        gateway.assert_health()
        # ensure that filewatch has run through the aborted config change logic
        wait()
        gateway.assert_health()
        response = gateway.get("gateway/routes/")
        assert response.json() == basic_routes


def test_server_update_config_removed_then_recreated(
    tmp_path: Path, basic_config_dict, basic_routes
):
    config = str(store_conf(tmp_path, "config.yaml", basic_config_dict))

    with Gateway(config) as gateway:
        response = gateway.get("gateway/routes/")
        assert response.json() == basic_routes
        # Give filewatch a moment to cycle
        wait()
        # remove config
        tmp_path.joinpath("config.yaml").unlink()
        wait()
        gateway.assert_health()

        store_conf(tmp_path, "config.yaml", {"routes": basic_config_dict["routes"][1:]})
        wait()
        response = gateway.get("gateway/routes/")
        assert response.json() == {"routes": basic_routes["routes"][1:]}


def test_server_static_endpoints(tmp_path, basic_config_dict, basic_routes):
    config = str(store_conf(tmp_path, "config.yaml", basic_config_dict))

    with Gateway(config) as gateway:
        response = gateway.get("gateway/routes/")
        assert response.json() == basic_routes

        for route in ["docs", "redoc"]:
            response = gateway.get(route)
            assert response.status_code == 200

        for index, route in enumerate(basic_config_dict["routes"]):
            response = gateway.get(f"gateway/routes/{route['name']}")
            assert response.json() == {"route": basic_routes["routes"][index]}


def test_server_dynamic_endpoints(tmp_path, basic_config_dict):
    config = str(store_conf(tmp_path, "config.yaml", basic_config_dict))

    with Gateway(config) as gateway:
        response = gateway.post(
            f"gateway/routes/{basic_config_dict['routes'][0]['name']}",
            json={"input": "Tell me a joke"},
        )
        assert response.json() == {"input": "Tell me a joke"}

        response = gateway.post(
            f"gateway/routes/{basic_config_dict['routes'][1]['name']}",
            json={"input": "Say hello", "temperature": 0.35},
        )
        assert response.json() == {"input": "Say hello", "temperature": 0.35}


def test_request_invalid_route(tmp_path, basic_config_dict):
    config = str(store_conf(tmp_path, "config.yaml", basic_config_dict))

    with Gateway(config) as gateway:
        # Test get
        response = gateway.get("gateway/routes/invalid/")
        assert response.status_code == 404
        assert response.json() == {
            "detail": "The route 'invalid' is not present or active on the server. Please "
            "verify the route name."
        }

        # Test post
        response = gateway.post("gateway/routes/invalid", json={"input": "should fail"})
        assert response.status_code == 405
        assert response.json() == {"detail": "Method Not Allowed"}
