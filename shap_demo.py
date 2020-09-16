import logging

import pandas as pd
import matplotlib.pyplot as plt
from sklearn.svm import SVC
from sklearn.datasets import load_iris
import shap

import mlflow.shap

logging.getLogger("shap").setLevel(logging.DEBUG)


def main2():
    with mlflow.start_run() as run:
        sklearn_model = ...
        # With this approach, the user needs to log a model first.
        # - What if the user doesn't need a model but just wants an explanation of the model?
        # - What if the user uses a model that we don't support (e.g. skorch)?
        mlflow.sklearn.log_model(sklearn_model, "model")
        model_uri = "runs/:{}/model".format(run.info.run_id)
        mlflow.shap.log_explanation(model_uri, data)


def main3():
    with mlflow.start_run() as run:
        random_model = ...
        # How can we detect `predict` or `predict_method`?
        # PyTorch models don't have a `predict` method.
        mlflow.shap.log_explanation(random_model, data)


model.shap.log_explanation(sklear_regressor.predict, features)
model.shap.log_explanation(sklearn_multi_classifier.predict_proba, features)


def predict_as_numpy_array(model, features):
    def predict(features):
        return model.predict(features).as_numpy_array()

    return predict


# This doesn't seem inconvenient that much...
model.shap.log_explanation(predict_as_numpy_array(model), features)


def main4():
    with mlflow.start_run() as run:
        random_model = ...
        # How can we detect `predict` or `predict_method`?
        # - sklearn's predict and predict_proba
        # - PyTorch models don't have a `predict` method. The model itself is a predict method.
        mlflow.shap.log_explanation(random_model, data)


def main():
    # train a multi-class classifier using the iris dataset
    X, y = load_iris(return_X_y=True, as_frame=True)

    # X = pd.concat((X,) * 1_0)
    # y = pd.concat((y,) * 1_0)

    print(X.shape)
    print(y.shape)
    model = SVC(kernel="rbf", probability=True)
    model.fit(X, y)

    # log an explanation
    with mlflow.start_run() as run:
        mlflow.shap.log_explanation(model.predict_proba, X)

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
