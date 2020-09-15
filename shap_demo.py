import logging

import pandas as pd
import matplotlib.pyplot as plt
from sklearn.svm import SVC
from sklearn.datasets import load_iris
import shap

import mlflow.shap

logging.getLogger("shap").setLevel(logging.DEBUG)


def main():
    # train a multi-class classifier using the iris dataset
    X, y = load_iris(return_X_y=True, as_frame=True)

    # X = pd.concat((X,) * 1_0)
    # y = pd.concat((y,) * 1_0)

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

    # log some plots using logged explanation data
    with mlflow.start_run(run_id=run.info.run_id):
        label_index_to_plot = 0

        # force plot
        force_plot_single0 = shap.force_plot(
            expl.expected_value[label_index_to_plot],
            expl.shap_values[label_index_to_plot][0, :],
            X.iloc[0, :],
        )
        force_plot_single1 = shap.force_plot(
            expl.expected_value[label_index_to_plot],
            expl.shap_values[label_index_to_plot][1, :],
            X.iloc[1, :],
        )
        force_plot_all = shap.force_plot(
            expl.expected_value[label_index_to_plot], expl.shap_values[label_index_to_plot], X
        )
        mlflow.shap._log_force_plot(force_plot_single0, "force_plot_single0.html")
        mlflow.shap._log_force_plot(force_plot_single1, "force_plot_single1.html")
        mlflow.shap._log_force_plot(force_plot_all, "force_plot_all.html")

        # summary plot
        shap.summary_plot(expl.shap_values[label_index_to_plot], X, show=False)
        summary_plot = plt.gcf()
        summary_plot.tight_layout()
        mlflow.shap._log_matplotlib_figure(summary_plot, "summary_plot.png")


if __name__ == "__main__":
    main()
