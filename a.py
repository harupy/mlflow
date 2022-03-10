import mlflow

nan = float("nan")

with mlflow.start_run():
    for idx, m in enumerate([0, 1, 2, nan, 4, 5, nan, nan, 6]):
        mlflow.log_metrics({"m": m}, step=idx)
