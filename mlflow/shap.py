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
    background_data=None,
    background_sampling_method="sample",
    background_num_samples=10,
):
    """
    Log an explanation.
    """

    if background_data is None and len(features) > 100:
        if background_sampling_method == "sample":
            background_data = shap.sample(features, background_num_samples)
        elif background_sampling_method == "kmeans":
            background_data = shap.kmeans(features, background_num_samples)
        else:
            msg_tpl = "Invalid value for `background_sampling_method`. Must be one of {} but got {}"
            raise ValueError(msg_tpl.format(["sample", "kmeans"], background_sampling_method))

    # compute shap_values
    explainer = shap.KernelExplainer(predict_func, background_data)
    shap_values = explainer.shap_values(features)

    expected_value = (
        np.array(explainer.expected_value)
        if isinstance(explainer.expected_value, list)
        else explainer.expected_value
    )

    # create a summary bar plot
    shap.summary_plot(shap_values, features, plot_type="bar", show=False)
    bar_plot = plt.gcf()
    bar_plot.tight_layout()

    # log results
    _log_numpy_object(np.array(shap_values), _SHAP_VALUES_FILE_NAME, _SHAP_DEFAULT_ARTIFACT_PATH)
    _log_numpy_object(expected_value, _EXPECTED_VALUE_FILE_NAME, _SHAP_DEFAULT_ARTIFACT_PATH)
    _log_matplotlib_figure(bar_plot, "bar_plot.png", _SHAP_DEFAULT_ARTIFACT_PATH)
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
