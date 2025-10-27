# File-based backend deprecation/removal in OSS MLflow

## Terminology

In this document, **"file-based backend"** refers to both the file-based tracking backend (mlflow/store/tracking/file_store.py) and model registry backend (mlflow/store/model_registry/file_store.py). These store data as files instead of in a database and are the current defaults for quick local prototyping.

## What is being deprecated?

The file-based backend is **currently the default** when you run MLflow without configuring a tracking URI or registry URI. In the future, the **database backend** (e.g., `sqlite:///mlruns.db`) will become the new default.

**Important**: The file-based backend is deprecated and will be removed. The File artifact repository (file-based artifact storage) will continue to be supported and is NOT deprecated.

**Current usage**: 42% of MLflow users (source: telemetry data) use the file-based backend.

## Why deprecate and remove the File-Based Backend?

The file-based backend is being deprecated and removed due to:

- **Maintenance Burden**

  - Every feature requires dual implementation (file-based backend + SQLAlchemy), significantly increasing development and testing time
  - Supporting both file-based and database storage backends slows down development and increases the risk of bugs

- **Limited Features & Poor UX**

  - Many modern MLflow features are not supported in the file-based backend:
    - Background jobs
    - Webhooks
    - (more to come)
  - Since the file-based backend is currently the default, these features are not available out-of-the-box, creating an inconvenient experience for users who need them

- **Security Risks**

  - Path traversal vulnerabilities have a larger attack surface than database-backed systems
  - Relies on OS-level file permissions which are inconsistent across platforms and harder to audit

- **Performance Issues**

  - Degrades significantly with >1,000 experiments or >10,000 runs
  - File system operations don't scale well compared to indexed database queries

## How to Migrate

First, back up your existing data (recommended):

```bash
cp -r ./mlruns ./mlruns_backup
```

Then migrate your file-based backend data to SQLite using the MLflow CLI:

```bash
mlflow <TBD> ./mlruns sqlite:///mlflow.db
```

Then update your tracking URI in your code or environment:

```python
# Before (file-based, deprecated)
import mlflow

# No configuration or mlflow.set_tracking_uri("./mlruns")

# After (SQLite, recommended)
import mlflow

mlflow.set_tracking_uri("sqlite:///mlflow.db")
```

**Notes:**

- Migration is non-destructive; your original data is preserved.
- The migration tool only supports migrating to a new, empty database, not merging with an existing one.
- Only metadata is migrated; artifact files remain in their original location.

## Task breakdown

| Task                            | Estimate | Notes                                                                        |
| :------------------------------ | :------- | :--------------------------------------------------------------------------- |
| Deprecation warning             | 0.125    | Add warning when file-based backend is used                                  |
| Create a migration tool / guide | 1.5      | Tool to migrate file-based backend data to SQLite                            |
| Communication plan execution    | 0.25     |                                                                              |
| Migrate tests \- OSS            | 0.5      | Update tests to use SQLite by default                                        |
| Migrate tests \- Universe       | 0.5      | Not urgent and can be delayed until we update mlflow version in MLR/DBR      |
| Switch defaults to SQLite       | 0.5      | Change default tracking & registry URIs to SQLite                            |
| Remove file backend             | 1.0      | Remove file-based backend implementations, clean up code, final test updates |

## Timeline

|                                                 | MLflow Version | ETA       |
| :---------------------------------------------- | :------------- | :-------- |
| Add a deprecation warning                       | 3.6            | 11/6/2025 |
| Switch defaults to sqlite (tracking & registry) | 3.7            | 12/4/2025 |
| Monitor telemetry & gather feedback             | 3.7 - 3.x      | TBD       |
| Remove file-based backend                       | 3.(x + 1)      | TBD       |

## What's impacted if we change the default tracking and registry URIs to a database backend?

- OSS MLflow
  - Tests
    - Most tests use the SQLite backend already, so the impact should be minimal, but some tests may need to be updated.
- Databricks
  - Tests
    - Some tests use the file-based backend when Databricks backend is unsupported. They might fail.
- Managed MLflow services (e.g. managed MLflow on Sagemaker)
  - I believe managed mlflow services use a database backend.

## FAQ

- **Does this change affect Databricks customers?**

  - Yes if they use the file-based backend for some reason. On Databricks, the tracking URI and registry URI are automatically set to "databricks" by default. The number of affected users is expected to be very small.

- **Can I continue using the file-based backend after v3.7?**
  - Yes, until v3.(x+1) (Q2 2026). You'll see deprecation warnings but the file-based backend will continue to work. We recommend migrating to SQLite during this period.
