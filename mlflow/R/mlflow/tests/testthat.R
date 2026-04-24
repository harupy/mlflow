# `trivial` is a dummy MLflow flavor that exists only for unit testing purposes

mlflow_save_model.trivial <- function(model, path, model_spec = list(), ...) {
  if (dir.exists(path)) unlink(path, recursive = TRUE)
  dir.create(path, recursive = TRUE)
  path <- normalizePath(path)

  trivial_conf = list(
    trivial = list(key1 = "value1", key2 = "value2")
  )
  model_spec$flavors <- c(model_spec$flavors, trivial_conf)
  mlflow:::mlflow_write_model_spec(path, model_spec)
}

mlflow_load_flavor.mlflow_flavor_trivial <- function(flavor, model_path) {
  list(flavor = flavor)
}

library(testthat)
library(mlflow)

# Allow extra time for the local SQLite-backed tracking server to come up
# (the first start runs alembic migrations).
options(mlflow.connect.wait = 30)

if (identical(Sys.getenv("NOT_CRAN"), "true")) {
  message("Current working directory: ", getwd())
  test_check("mlflow", reporter = ProgressReporter)
}
