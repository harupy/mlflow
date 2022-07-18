import mlflow
import random
import uuid


def log():
    for _ in range(10):
        with mlflow.start_run():
            mlflow.log_params({"p1": random.random(), "p2": random.random()})
            mlflow.log_metrics({"m1": random.random(), "m2": random.random()})
            mlflow.set_tags({"t1": uuid.uuid4().hex, "m2": uuid.uuid4().hex})


mlflow.set_experiment("a")
log()
mlflow.set_experiment("b")
log()
mlflow.set_experiment("c")
