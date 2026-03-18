"""
Bug 2: Empty uv project dependencies cause false fallback to package-capture inference.

When a uv project has zero dependencies, `uv export` returns empty output.
`export_uv_requirements()` correctly returns `[]` (empty list).
But in `infer_pip_requirements()`, the walrus operator:

    if uv_requirements := export_uv_requirements(...)

evaluates `[]` as falsy, so the code falls through to the warning:
"uv export failed or returned no requirements."
It then falls back to package-capture inference, which may pick up
unrelated packages from the current environment.

This means even though the user has a valid uv project with intentionally
zero dependencies, MLflow ignores it and infers potentially wrong deps.
"""

import logging
import os
import sys
from pathlib import Path

mlflow_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(mlflow_root))

import mlflow
import mlflow.pyfunc
from mlflow.utils.uv_utils import detect_uv_project, export_uv_requirements

EMPTY_DEPS_DIR = Path(__file__).parent / "empty-deps"


def demonstrate_bug():
    print("Bug 2: Empty requirements list treated as failure")
    print("=" * 60)

    # Step 1: Show the uv project is valid
    project = detect_uv_project(EMPTY_DEPS_DIR)
    print(f"\nuv project detected: {project is not None}")
    print(f"  uv.lock: {project.uv_lock}")
    print(f"  pyproject.toml: {project.pyproject}")

    # Step 2: Show uv export returns empty list
    requirements = export_uv_requirements(EMPTY_DEPS_DIR)
    print(f"\nuv export result: {requirements!r}")
    print(f"  type: {type(requirements).__name__}")
    print(f"  truthiness: {bool(requirements)}")

    # Step 3: Show the walrus operator bug
    print("\nThe walrus operator `if uv_requirements := export_uv_requirements(...):`")
    print(f"  [] is falsy: {not []}")
    print("  So the code falls through to the 'uv export failed' warning")
    print("  and falls back to package-capture inference.")

    # Step 4: Show what happens when logging a model
    print("\nDemonstrating through model logging:")
    print("-" * 40)

    os.chdir(EMPTY_DEPS_DIR)

    class SimpleModel(mlflow.pyfunc.PythonModel):
        def predict(self, context, model_input, params=None):
            return model_input

    db_path = Path(__file__).parent / "mlflow_bug2.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("bug2-empty-deps")

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("mlflow")
    logger.setLevel(logging.WARNING)

    with mlflow.start_run(run_name="empty-deps-test") as run:
        mlflow.pyfunc.log_model(
            python_model=SimpleModel(),
            name="model",
        )

        artifact_path = mlflow.artifacts.download_artifacts(
            run_id=run.info.run_id, artifact_path="model"
        )
        requirements_file = Path(artifact_path) / "requirements.txt"
        requirements = requirements_file.read_text().strip()

        print("\nrequirements.txt from logged model:")
        if requirements:
            for line in requirements.splitlines():
                print(f"  {line}")
            print(
                "\nBUG: The uv project has zero dependencies, but MLflow fell back"
                "\nto package-capture inference and picked up packages from the"
                "\ncurrent environment."
            )
        else:
            print("  (empty - correct behavior)")


if __name__ == "__main__":
    demonstrate_bug()
