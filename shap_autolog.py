import gorilla
import numpy as np
import shap
from sklearn.linear_model import LinearRegression

from mlflow.utils.autologging_utils import wrap_patch

AUTO_SHAP = False


def shap_autolog():
    """
    Enable autologging for SHAP.
    """
    global AUTO_SHAP
    AUTO_SHAP = True


def sklearn_autolog():
    """
    Enable autologging for scikit-learn.

    Note that this is a simplified version of `mlflow.sklearn.autolog`.
    """

    def fit(self, *args, **kwargs):
        original_fit = gorilla.get_original_attribute(self, "fit")
        fitted_estimator = original_fit(*args, **kwargs)

        if AUTO_SHAP:
            X = args[0] if len(args) > 0 else kwargs.get("X")
            explainer = shap.KernelExplainer(fitted_estimator.predict, X)
            shap_values = explainer.shap_values(X)
            ...
            print(shap_values)

        return fitted_estimator

    wrap_patch(LinearRegression, "fit", fit)


# enable auto-logging for scikit-learn & shap
shap_autolog()
sklearn_autolog()

# train a linear regression model
X = np.array([[1, 2], [3, 4]])
y = np.array([5, 6])
model = LinearRegression()

with mlflow.start_run():
    model.fit(X, y)

# output:
# [[-0.25 -0.25]
#  [ 0.25  0.25]
