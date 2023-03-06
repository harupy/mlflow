import os
import uuid

import mlflow
from mlflow.server.auth import AuthClient


class User:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.client = AuthClient("http://localhost:5000", username, password)

    def __enter__(self):
        os.environ["MLFLOW_TRACKING_USERNAME"] = self.username
        os.environ["MLFLOW_TRACKING_PASSWORD"] = self.password

    def __exit__(self, exc_type, exc_value, traceback):
        os.environ["MLFLOW_TRACKING_USERNAME"] = ""
        os.environ["MLFLOW_TRACKING_PASSWORD"] = ""


def assert_fail(f):
    try:
        f()
        raise AssertionError("Should fail")
    except Exception as e:
        print(f"Expected failure: {e}")


a = User("user_a", "pass_a")
b = User("user_b", "pass_b")


mlflow.set_tracking_uri("http://localhost:5000")

name_a = f"a_{uuid.uuid4().hex}"
assert_fail(lambda: mlflow.create_experiment(name_a))

with a:
    exp_id_a = mlflow.create_experiment(name_a)
    assert a.client.get_experiment_permission(exp_id_a, a.username)["permission"] == "MANAGE"

name_b = f"b_{uuid.uuid4().hex}"
with b:
    assert_fail(lambda: b.client.get_experiment_permission(exp_id_a, a.username))
    assert_fail(lambda: mlflow.get_experiment(exp_id_a))
    mlflow.create_experiment(name_b)


with a:
    a.client.update_experiment_permission(exp_id_a, b.username, "READ")
    print(mlflow.get_experiment(exp_id_a))
