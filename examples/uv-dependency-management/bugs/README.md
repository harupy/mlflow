# Bug Report: MLflow uv Dependency Management

This directory contains reproducible examples demonstrating bugs in MLflow's uv dependency management feature (`mlflow.utils.uv_utils`).

## Summary of Findings

### Bug 1: Workspace members leak into requirements.txt (Critical)

**File:** `bug1_workspace_leak.py`

MLflow uses `uv export --no-emit-project` to generate pinned requirements. However, `--no-emit-project` only suppresses the **root** project. In a uv workspace, **workspace member packages** still appear in the output as editable installs (e.g., `-e ./packages/my-lib`).

These local paths don't exist on other machines, so `pip install -r requirements.txt` fails when loading the model — **breaking model portability**.

**Root cause:** `export_uv_requirements()` in `uv_utils.py:176` uses `--no-emit-project` instead of `--no-emit-workspace`.

**Fix:** Replace `--no-emit-project` with `--no-emit-workspace` in the `uv export` command.

```
# Current (broken):     --no-emit-project
# Fixed:                --no-emit-workspace
```

---

### Bug 2: Empty requirements list triggers false fallback (Medium)

**File:** `bug2_empty_requirements.py`

When a uv project has zero dependencies, `uv export` returns empty output. `export_uv_requirements()` correctly returns `[]`, but in `infer_pip_requirements()` (environment.py:452), the walrus operator:

```python
if uv_requirements := export_uv_requirements(directory):
    return uv_requirements
```

evaluates `[]` as **falsy**, causing the code to fall through to: _"uv export failed or returned no requirements. Falling back to package capture based inference."_

The user has a valid uv project with intentionally zero dependencies, but MLflow ignores it and infers potentially wrong dependencies from the current environment.

**Root cause:** `[]` is falsy in Python, and the walrus operator treats it the same as `None`.

**Fix:** Check for `None` explicitly instead of relying on truthiness:

```python
uv_requirements = export_uv_requirements(directory)
if uv_requirements is not None:
    ...
```

---

### Bug 3: Explicit uv_project_path silently falls back on invalid path (Medium)

**File:** `bug3_silent_fallback.py`

When a user explicitly passes `uv_project_path="/nonexistent/path"`, the code silently falls back to standard package-capture inference instead of raising an error. The user thinks they're getting reproducible uv-locked dependencies, but they're actually getting inferred dependencies.

**Root cause:** `detect_uv_project()` returns `None` for invalid paths, and the calling code doesn't distinguish between "auto-detect found nothing" and "user's explicit path was invalid."

**Fix:** When `uv_project_path` is explicitly set, raise `MlflowException` if the path doesn't exist or doesn't contain a valid uv project.

---

### Bug 4: Workspace pyproject.toml breaks model environment restore (Critical)

**File:** `bug4_workspace_restore.py`

When logging a model from a uv workspace, `copy_uv_project_files()` copies the root `pyproject.toml` which contains `[tool.uv.workspace]` configuration with `members = ["packages/*"]`.

When restoring the environment via `uv sync --frozen`, uv tries to find those workspace member directories which **don't exist** in the model artifacts directory, causing `uv sync` to fail.

**Root cause:** The raw workspace `pyproject.toml` is copied without stripping workspace-specific configuration.

**Fix:** Either:

- Strip `[tool.uv.workspace]` and `[tool.uv.sources]` from the copied `pyproject.toml`
- Always generate a minimal `pyproject.toml` via `create_uv_sync_pyproject()` instead of copying the original
- Use `--no-emit-workspace` in export and don't rely on the original `pyproject.toml` for restore

---

## Reproduction

All examples can be run from the MLflow repository root:

```bash
# Bug 1: Workspace members leak
uv run python examples/uv-dependency-management/bugs/bug1_workspace_leak.py

# Bug 2: Empty requirements fallback
uv run python examples/uv-dependency-management/bugs/bug2_empty_requirements.py

# Bug 3: Silent fallback on invalid path
uv run python examples/uv-dependency-management/bugs/bug3_silent_fallback.py

# Bug 4: Workspace restore failure
uv run python examples/uv-dependency-management/bugs/bug4_workspace_restore.py
```

## Environment

- MLflow: 3.11.1.dev0 (from source, SHA: `9fd1221883`)
- uv: 0.9.8
- Python: 3.10.19
