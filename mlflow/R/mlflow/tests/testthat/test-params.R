context("Params")

test_that("mlflow can read typed command line parameters", {
  mlflow_clear_test_dir("mlruns")

  mlflow_cli(
    "run",
    "examples/",
    "--env-manager",
    "uv",
    "--entry-point",
    "params_example.R",
    "-P", "my_int=10",
    "-P", "my_num=20.0",
    "-P", "my_str=XYZ"
  )

  runs <- mlflow_search_runs(experiment_ids = "0")
  expect_true(nrow(runs) >= 1)
  param_keys <- runs$params[[1]]$key
  expect_true("my_int" %in% param_keys)
  expect_true("my_num" %in% param_keys)
  expect_true("my_str" %in% param_keys)
})

test_that("ml_param() type checking works", {
  expect_identical(mlflow_param("p1", "a", "string"), "a")
  expect_identical(mlflow_param("p2", 42, "integer"), 42L)
  expect_identical(mlflow_param("p3", 42L), 42L)
  expect_identical(mlflow_param("p4", 12), 12)
})
