import pytest

from mlflow.exceptions import MlflowException
import mlflow.spark
from tests.spark.autologging.utils import _get_or_create_spark_session


@pytest.mark.large
def test_enabling_autologging_throws_for_missing_jar():
    # pylint: disable=unused-argument
    spark_session = _get_or_create_spark_session(jars="")
    try:
        with pytest.raises(MlflowException, match="ensure you have the mlflow-spark JAR attached"):
            mlflow.spark.autolog()
    finally:
        spark_session.stop()
