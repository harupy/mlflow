import os
from collections import namedtuple
from contextlib import contextmanager
import tempfile
import yaml

import matplotlib.pyplot as plt
import mlflow
import numpy as np
import shap


_SHAP_DEFAULT_ARTIFACT_PATH = "shap"
_SHAP_VALUES_FILE_NAME = "shap_values.npy"
_EXPECTED_VALUE_FILE_NAME = "expected_value.npy"


@contextmanager
def _log_artifact_contextmanager(out_file, artifact_path=None):
    """
    A context manager to make it easier to log files.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = os.path.join(tmp_dir, out_file)
        yield tmp_path
        mlflow.log_artifact(tmp_path, artifact_path)


def _log_numpy_object(np_obj, out_file, artifact_path=None):
    """
    Log a numpy object.
    """
    assert out_file.endswith(".npy")

    with _log_artifact_contextmanager(out_file, artifact_path) as tmp_path:
        np.save(tmp_path, np_obj)


def _log_matplotlib_figure(fig, out_file, artifact_path=None):
    """
    Log a matplotlib figure.
    """
    with _log_artifact_contextmanager(out_file, artifact_path) as tmp_path:
        fig.savefig(tmp_path)
        plt.close(fig)


def _log_force_plot(force_plot, out_file, artifact_path=None):
    """
    Log a force plot.
    """
    assert out_file.endswith(".html")

    with _log_artifact_contextmanager(out_file, artifact_path) as tmp_path:
        shap.save_html(tmp_path, force_plot, full_html=True)


def _log_dict_as_yml(dct, out_file, artifact_path=None):
    assert out_file.endswith(".yml") or out_file.endswith(".yaml")

    with _log_artifact_contextmanager(out_file, artifact_path) as tmp_path:
        with open(tmp_path, "w") as f:
            f.write(yaml.dump(dct, default_flow_style=False))


def log_explanation(
    predict_func,
    features,
    # explainer_constructor=KerneExplainer,
    # constructor_kwargs=None,  # defaults to an empty dict
    # shap_values_kwargs=None,  # defaults to an empty dict
    # the following arguments are only valid when `explainer_constructor` is `KerneExplainer`
):
    """
    Log an explanation.

    shap_values_kwargs is used when
    ```
    explainer = explainer_constructor(predict_func, **constructor_kwargs)
    shap_values = explainer.shap_values(features, **shap_values_kwargs)
    ```
    """
    # compute shap_values
    # QUESTION: what is the proper sampling size for `background_data`
    # Some explainers (e.g. `TreeExplainer`) doesn't require `background_data`
    # `shap` raises a warning saying "use shap.sample or shap.kmeans"
    # when `background_data` has more than 100 rows.
    explainer = shap.KernelExplainer(predict_func, background_data)

    # this step takes long if the data size is large
    # For a regression or binary classification model,
    # `shap_values` becomes a 2D array which has the shape: (num_samples x num_features).
    # For a multi-class classification model,
    # `shap_values` becomes a 3D array which has the shape: (num_classes x num_samples x num_features)
    # We can slice a 3D array and save each layer in one csv file, but this approach doesn't seem to
    # work when the number of classes is large.
    # It the size of `features` is large, it takes really long time to compute SHAP values.
    # We can sample `features` to avoid that, but not sure if that' what we should do.
    # QUESTION: should we log `features`? Basically, (expected_value, shap_values, features)
    # is like a set. Logging `features` with `shap_values` and `expected_value` allows the user
    # to create additional plots easily. If we didn't log `features`, the user would somehow need to
    # prepare `features` used when computing the SHAP values.
    shap_values = explainer.shap_values(features)
    shap_values = np.array(shap_values)

    # `expected_value` is a number or a list of number (multi-class classification)
    # `expected_value` equals to `predict_func(features).mean(axis=0)`
    # For a regression or binary classification model, `expected_value` becomes a number
    # For a multi-class classification model, `expected_value` becomes a list of numbers
    expected_value = (
        np.array(explainer.expected_value)
        if isinstance(explainer.expected_value, list)
        else explainer.expected_value
    )

    # log explanation data
    _log_numpy_object(shap_values, _SHAP_VALUES_FILE_NAME, _SHAP_DEFAULT_ARTIFACT_PATH)
    _log_numpy_object(expected_value, _EXPECTED_VALUE_FILE_NAME, _SHAP_DEFAULT_ARTIFACT_PATH)

    # create a summary plot
    # `summary_plot` returns nothing
    shap.summary_plot(shap_values, features, plot_type="bar", show=False)
    bar_plot = plt.gcf()  # get the current figure
    bar_plot.tight_layout()  # prevent the y-axis labels from overflowing
    _log_matplotlib_figure(bar_plot, "bar_plot.png", _SHAP_DEFAULT_ARTIFACT_PATH)

    # log metadata
    _log_dict_as_yml(
        {
            "shap_version": shap.__version__,
            "explainer": shap.KernelExplainer.__name__ + "Explainer",
            "features_shape": str(features.shape),
        },
        "metadata.yml",
        _SHAP_DEFAULT_ARTIFACT_PATH,
    )


def load_explanation(run_id, artifact_path=None):
    """
    Load an explanation.
    """
    artifact_path = _SHAP_DEFAULT_ARTIFACT_PATH if artifact_path is None else artifact_path
    with tempfile.TemporaryDirectory() as tmp_dir:
        client = mlflow.tracking.MlflowClient()
        client.download_artifacts(run_id, artifact_path, dst_path=tmp_dir)

        Explanation = namedtuple("Explanation", ["shap_values", "expected_value"])
        shap_values = np.load(
            os.path.join(tmp_dir, _SHAP_DEFAULT_ARTIFACT_PATH, _SHAP_VALUES_FILE_NAME)
        )
        expected_value = np.load(
            os.path.join(tmp_dir, _SHAP_DEFAULT_ARTIFACT_PATH, _EXPECTED_VALUE_FILE_NAME)
        )
        return Explanation(shap_values=shap_values, expected_value=expected_value)
