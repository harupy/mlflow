import os
import uuid
import tempfile
from pathlib import Path

import mlflow


tmpdir = tempfile.mkdtemp()

# setup a temporary experiment
tracking_uri = "file://{}".format(os.path.join(tmpdir, "mlruns"))
mlflow.set_tracking_uri(tracking_uri)

expr_name = uuid.uuid4().hex
artifact_location = "ftp://mlflow:mlflow@localhost:21/mlflow"
mlflow.create_experiment(expr_name, artifact_location=artifact_location)
mlflow.set_experiment(expr_name)

# create files to log
p = Path(tmpdir).joinpath("files")
p.mkdir()
p.joinpath("a.txt").write_text("a")
p.joinpath("b.txt").write_text("b")
p.joinpath("subdir").mkdir()
p.joinpath("subdir").joinpath("c.txt").write_text("c")
p.joinpath("subdir").joinpath("d.txt").write_text("d")
p.joinpath("empty").mkdir()

# log files with `artifact_path`
with mlflow.start_run() as run:
    mlflow.log_artifacts(p.absolute(), artifact_path="artifacts")


def yield_artifacts(run_id, path=None):
    client = mlflow.tracking.MlflowClient()
    for item in client.list_artifacts(run_id, path):
        if item.is_dir:
            yield item.path
            yield from yield_artifacts(run_id, item.path)
        else:
            yield item.path


# show artifacts
for a in yield_artifacts(run.info.run_id):
    print(a)
