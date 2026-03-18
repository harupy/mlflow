"""
Bug 4: Workspace pyproject.toml artifact breaks model environment restore.

When logging a model from a uv workspace, `copy_uv_project_files()` copies
the root pyproject.toml which contains `[tool.uv.workspace]` configuration
with `members = ["packages/*"]`. When restoring the model environment via
`uv sync --frozen`, uv tries to find those workspace member directories
which don't exist in the model artifacts, causing uv sync to fail.

The model artifacts directory contains:
  - uv.lock (from workspace root)
  - pyproject.toml (from workspace root, with workspace config!)
  - .python-version

But NOT:
  - packages/my-lib/ (workspace member)

So `uv sync` fails because the workspace member doesn't exist.
"""

import sys
import tempfile
from pathlib import Path

mlflow_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(mlflow_root))

from mlflow.utils.uv_utils import (
    _PYPROJECT_FILE,
    copy_uv_project_files,
    run_uv_sync,
    setup_uv_sync_environment,
)

WORKSPACE_DIR = Path(__file__).parent / "workspace-leak"


def demonstrate_bug():
    print("Bug 4: Workspace pyproject.toml breaks model environment restore")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Step 1: Copy uv project files (simulating what MLflow does at log time)
        model_dir = tmpdir / "model"
        model_dir.mkdir()

        print("\n1. Copying workspace uv files to model artifacts...")
        result = copy_uv_project_files(model_dir, WORKSPACE_DIR)
        print(f"   copy_uv_project_files returned: {result}")

        # Show the copied pyproject.toml has workspace config
        pyproject_content = (model_dir / _PYPROJECT_FILE).read_text()
        print("\n2. Copied pyproject.toml content:")
        for line in pyproject_content.splitlines():
            print(f"   {line}")

        has_workspace = "[tool.uv.workspace]" in pyproject_content
        print(f"\n   Contains [tool.uv.workspace]: {has_workspace}")
        if has_workspace:
            print("   BUG: Workspace config references local paths that won't exist!")

        # Step 3: Try to set up uv sync environment (simulating model load)
        env_dir = tmpdir / "env"
        print("\n3. Setting up uv sync environment...")
        setup_result = setup_uv_sync_environment(env_dir, model_dir, "3.11.9")
        print(f"   setup_uv_sync_environment returned: {setup_result}")

        # Step 4: Show the env pyproject.toml still has workspace config
        env_pyproject = (env_dir / _PYPROJECT_FILE).read_text()
        has_workspace_in_env = "[tool.uv.workspace]" in env_pyproject
        print(f"\n4. Env pyproject.toml has workspace config: {has_workspace_in_env}")

        if has_workspace_in_env:
            print("   BUG: The env pyproject.toml references workspace members")
            print("   that don't exist in the model artifacts!")

            # Step 5: Try to run uv sync (should fail)
            print("\n5. Attempting uv sync --frozen (should fail)...")
            sync_result = run_uv_sync(env_dir, frozen=True, no_dev=True, capture_output=True)
            print(f"   uv sync returned: {sync_result}")
            if not sync_result:
                print("   CONFIRMED: uv sync failed because workspace members don't exist!")
                print("   Models logged from uv workspaces cannot be restored.")


if __name__ == "__main__":
    demonstrate_bug()
