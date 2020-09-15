import logging

from sklearn.svm import SVC
from sklearn.datasets import load_iris
import shap

import mlflow.shap

logging.getLogger("shap").setLevel(logging.DEBUG)


def main():
    import pandas as pd

    # train a model
    X, y = load_iris(return_X_y=True, as_frame=True)

    X = pd.concat((X,) * 1_0)
    y = pd.concat((y,) * 1_0)

    print(X.shape)
    print(y.shape)
    svm = SVC(kernel="rbf", probability=True)
    svm.fit(X, y)

    # log an explanation
    with mlflow.start_run() as run:
        mlflow.shap.log_explanation(svm.predict_proba, X)

    # load the explanation
    expl = mlflow.shap.load_explanation(run.info.run_id)
    print(expl.expected_value.shape)
    print(expl.shap_values.shape)

    # create force plots using the loaded expalanation data and log them
    with mlflow.start_run(run_id=run.info.run_id):
        # create force plots
        force_plot_single = shap.force_plot(
            expl.expected_value[0], expl.shap_values[0][0, :], X.iloc[0, :]
        )
        force_plot_all = shap.force_plot(expl.expected_value[0], expl.shap_values[0], X)

        # log force plots
        mlflow.shap._log_force_plot(force_plot_single, "force_plot_single.html")
        mlflow.shap._log_force_plot(force_plot_all, "force_plot_all.html")


if __name__ == "__main__":
    main()
