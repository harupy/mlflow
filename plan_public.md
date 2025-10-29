# Filesystem backend deprecation in OSS MLflow

## What's Being Deprecated?

- The filesystem backend (e.g., `tracking_uri='./mlruns'`) is deprecated. The database backend (`sqlite:///mlruns.db`) will be the new default.
- Filesystem **artifact** storage remains fully supported and can continue to pair with a database backend.

## Why deprecate Filesystem Backend?

The filesystem backend is deprecated due to:

- **Maintenance Burden**

  - Every feature requires dual implementation (filesystem + database), significantly increasing development and testing time
  - Supporting both filesystem and database storage backends slows down development and increases the risk of bugs

- **Limited Features & Poor UX**

  - Many new MLflow features are not supported in the filesystem backend. Since the filesystem backend is currently the default, these features are not available out-of-the-box, creating an inconvenient experience for users who need them

    | Feature                            | File Backend | Database Backend |
    | ---------------------------------- | :----------: | :--------------: |
    | Experiments / Tags                 |      ✅      |        ✅        |
    | Runs (info, params, metrics, tags) |      ✅      |        ✅        |
    | Run inputs/outputs                 |      ✅      |        ✅        |
    | Logged models                      |      ✅      |        ✅        |
    | Traces (metadata, assessments)     |      ✅      |        ✅        |
    | Model registry                     |      ✅      |        ✅        |
    | Trace spans (OTel data)            |      ➖      |        ✅        |
    | Evaluation datasets / results      |      ➖      |        ✅        |
    | Model registry webhooks            |      ➖      |        ✅        |
    | Registered-model scorers           |      ➖      |        ✅        |

- **Security Risks**

  - Path traversal vulnerabilities have a larger attack surface than database-backed systems
  - Relies on OS-level file permissions which are inconsistent across platforms and harder to audit

- **Performance Issues**

  - Degrades significantly with a high volume of runs/experiments/models
  - File system operations don't scale well compared to indexed database queries

## Timeline

**Note: The timeline below is tentative and subject to change based on community feedback.**

| Event                     | MLflow Version | Target date    |
| :------------------------ | :------------- | :------------- |
| Add a deprecation warning | 3.6            | Early Nov 2025 |
| Switch defaults to sqlite | 3.7            | Early Dec 2025 |

## FAQ

- **How will I know if I'm using the filesystem backend?**

  - If you don't explicitly set a tracking URI, or if you use `mlflow.set_tracking_uri("./mlruns")` or similar file paths, you're using the filesystem backend.

- **What will happen to my existing data?**

  - Your existing data will remain intact. We'll provide a migration tool to help you transfer your data from the filesystem backend to SQLite when it's ready.

- **Will this affect my workflows?**

  - The change is primarily in how metadata is stored. Your code will need minimal changes (updating the tracking URI). Artifact storage and most MLflow APIs remain the same.

- **Can I continue using the filesystem backend?**

  - Yes, the filesystem backend will continue to work with deprecation warnings. We're gathering community feedback before making any further changes.

## We Want Your Feedback

Before proceeding, we want to hear from the community:

- How would this change impact your workflows?
- What challenges do you anticipate with migration?
- Are there scenarios where the filesystem backend is critical for you?

Please share your feedback, concerns, or suggestions in the comments below.
