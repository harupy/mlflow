import mlflow

from sklearn.linear_model import LinearRegression


X = [[1, 2], [3, 4]]
y = [5, 6]
model = LinearRegression().fit(X, y)


with mlflow.start_run() as run:
    mlflow.sklearn.log_model(model, "model")

loaded = mlflow.pyfunc.load_model("runs:/{run_id}/model".format(run_id=run.info.run_id))

print(loaded.predict(X))
