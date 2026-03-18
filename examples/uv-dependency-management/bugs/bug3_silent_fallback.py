"""
Bug 3: Explicit uv_project_path to invalid directory silently falls back.

When a user explicitly sets `uv_project_path="/some/nonexistent/path"`,
instead of raising an error, the code silently falls back to standard
package-capture inference. The user thinks they're getting reproducible
uv-locked dependencies, but they're actually getting inferred dependencies.

The code flow:
1. `uv_project_path is not None` -> True, so enter the uv branch
2. `detect_uv_project(uv_project_dir)` -> None (no uv.lock/pyproject.toml)
3. No error raised - silently falls through to package-capture inference
4. User gets wrong dependencies without any indication

This is dangerous because the user explicitly opted in to uv support
for a specific path. If that path doesn't work, they should be told.
"""

import sys
import tempfile
from pathlib import Path

mlflow_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(mlflow_root))

import mlflow
import mlflow.pyfunc


def demonstrate_bug():
    print("Bug 3: Silent fallback when explicit uv_project_path is invalid")
    print("=" * 60)

    class SimpleModel(mlflow.pyfunc.PythonModel):
        def predict(self, context, model_input, params=None):
            return model_input

    db_path = Path(__file__).parent / "mlflow_bug3.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("bug3-silent-fallback")

    # Test with a completely nonexistent path
    bad_path = "/tmp/this/path/does/not/exist"
    print(f"\nAttempting to log model with uv_project_path={bad_path!r}")
    print("Expected: An error telling the user the path is invalid")
    print("Actual: Silent fallback to standard inference (no error!)")
    print()

    try:
        with mlflow.start_run(run_name="bad-path-test") as run:
            mlflow.pyfunc.log_model(
                python_model=SimpleModel(),
                name="model",
                uv_project_path=bad_path,
            )

            artifact_path = mlflow.artifacts.download_artifacts(
                run_id=run.info.run_id, artifact_path="model"
            )
            requirements_file = Path(artifact_path) / "requirements.txt"
            requirements = requirements_file.read_text().strip()

            print("BUG: No error was raised! Model was logged with fallback dependencies:")
            for line in requirements.splitlines():
                print(f"  {line}")
            print(
                "\nThe user explicitly asked for uv deps from a specific path,"
                "\nbut got standard inferred deps instead. No warning was shown."
            )
    except Exception as e:
        print(f"Expected error raised: {e}")
        print("(This is correct behavior - the path should be validated)")

    # Test with a path that exists but has no uv project files
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n\nAttempting with path that exists but has no uv.lock: {tmpdir}")
        try:
            with mlflow.start_run(run_name="no-uv-files-test") as run:
                mlflow.pyfunc.log_model(
                    python_model=SimpleModel(),
                    name="model",
                    uv_project_path=tmpdir,
                )

                artifact_path = mlflow.artifacts.download_artifacts(
                    run_id=run.info.run_id, artifact_path="model"
                )
                uv_lock_exists = (Path(artifact_path) / "uv.lock").exists()

                print("BUG: No error raised! Model logged without uv artifacts.")
                print(f"  uv.lock in artifacts: {uv_lock_exists}")
                print(
                    "  The user explicitly asked for uv support but got"
                    "\n  standard inference instead."
                )
        except Exception as e:
            print(f"Error raised: {e}")


if __name__ == "__main__":
    demonstrate_bug()
