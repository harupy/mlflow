"""
Bug 1: Workspace member packages leak into requirements.txt

MLflow uses `uv export --no-emit-project` but this only suppresses the ROOT project.
In a uv workspace, workspace MEMBER packages still appear in the output as editable
installs (e.g. `-e ./packages/my-lib`). These local paths don't exist when loading
the model on another machine, causing `pip install -r requirements.txt` to fail.

Fix: Use `--no-emit-workspace` instead of `--no-emit-project`.
"""

import os
import sys
from pathlib import Path

# Add mlflow to path
mlflow_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(mlflow_root))

import mlflow
import mlflow.pyfunc
from mlflow.utils.uv_utils import export_uv_requirements

WORKSPACE_DIR = Path(__file__).parent / "workspace-leak"


def demonstrate_bug():
    print("Bug 1: Workspace members leak into requirements.txt")
    print("=" * 60)

    # Show what MLflow's uv export produces
    requirements = export_uv_requirements(WORKSPACE_DIR)

    print("\nRequirements from uv export (MLflow's current behavior):")
    editable_entries = []
    for req in requirements:
        marker = ""
        if req.startswith("-e ") or req.startswith("."):
            marker = "  <-- BUG: local path, will break on other machines!"
            editable_entries.append(req)
        print(f"  {req}{marker}")

    if editable_entries:
        print(f"\nBUG CONFIRMED: {len(editable_entries)} workspace member(s) leaked:")
        for entry in editable_entries:
            print(f"  {entry}")
        print(
            "\nThis will cause `pip install -r requirements.txt` to fail when"
            "\nloading this model on another machine because the local path"
            "\n`./packages/my-lib` won't exist."
        )
        print("\nFix: Use `--no-emit-workspace` instead of `--no-emit-project`")
    else:
        print("\nNo leaked workspace members (bug may have been fixed).")


def demonstrate_model_logging_bug():
    print("\n\nDemonstrating the bug through mlflow.pyfunc.log_model():")
    print("-" * 60)

    os.chdir(WORKSPACE_DIR)

    class SimpleModel(mlflow.pyfunc.PythonModel):
        def predict(self, context, model_input, params=None):
            return model_input

    db_path = Path(__file__).parent / "mlflow_bug1.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("bug1-workspace-leak")

    with mlflow.start_run(run_name="workspace-leak-test") as run:
        mlflow.pyfunc.log_model(
            python_model=SimpleModel(),
            name="model",
        )

        artifact_path = mlflow.artifacts.download_artifacts(
            run_id=run.info.run_id, artifact_path="model"
        )
        requirements_file = Path(artifact_path) / "requirements.txt"
        requirements = requirements_file.read_text()

        print("\nrequirements.txt content (from logged model):")
        for line in requirements.strip().splitlines():
            marker = ""
            if line.startswith("-e ") or "./packages" in line:
                marker = "  <-- BUG!"
            print(f"  {line}{marker}")

        has_local_paths = any(
            "-e " in line or "./packages" in line for line in requirements.splitlines()
        )
        if has_local_paths:
            print("\nBUG: Model requirements contain local workspace paths!")
            print("This model cannot be loaded on another machine.")
        else:
            print("\nNo local paths found (bug may have been fixed).")


if __name__ == "__main__":
    demonstrate_bug()
    demonstrate_model_logging_bug()
