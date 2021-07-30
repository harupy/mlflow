from mlflow.utils.versioning_utils import _strip_local_version_identifier


def test_strip_local_version_identifier():
    assert _strip_local_version_identifier("1.2.3") == "1.2.3"
    assert _strip_local_version_identifier("1.2.3+ab45") == "1.2.3"
    assert _strip_local_version_identifier("1.2.3rc0+ab45") == "1.2.3rc0"
    assert _strip_local_version_identifier("1.2.3.dev0+ab45") == "1.2.3.dev0"
    assert _strip_local_version_identifier("1.2.3.post0+ab45") == "1.2.3.post0"
