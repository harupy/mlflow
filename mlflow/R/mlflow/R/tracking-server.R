#' @importFrom httpuv startDaemonizedServer
#' @importFrom httpuv stopServer
mlflow_port_available <- function(port) {
  tryCatch({
    handle <- httpuv::startDaemonizedServer("127.0.0.1", port, list())
    httpuv::stopServer(handle)
    TRUE
  }, error = function(e) {
    FALSE
  })
}

#' @importFrom openssl rand_num
mlflow_connect_port <- function() {
  port <- getOption(
    "mlflow.port",
    NULL
  )

  retries <- getOption("mlflow.port.retries", 10)
  while (is.null(port) && retries > 0) {
    port <- floor(5000 + rand_num(1) * 1000)
    if (!mlflow_port_available(port)) {
      port <- NULL
    }

    retries <- retries - 1
  }

  port
}

mlflow_cli_param <- function(args, param, value) {
  if (!is.null(value)) {
    args <- c(
      args,
      param,
      value
    )
  }

  args
}

#' Run MLflow Tracking Server
#'
#' Wrapper for `mlflow server`.
#'
#' @param file_store Deprecated. Use `backend_store_uri` instead. The root of the
#'   backing file store for experiment and run data. Cannot be combined with
#'   `backend_store_uri`.
#' @param default_artifact_root Local or S3 URI to store artifacts in, for newly created experiments.
#' @param host The network address to listen on (default: 127.0.0.1).
#' @param port The port to listen on (default: 5000).
#' @param workers Number of gunicorn worker processes to handle requests (default: 4).
#' @param static_prefix A prefix which will be prepended to the path of all static paths.
#' @param serve_artifacts A flag specifying whether or not to enable artifact serving (default: FALSE).
#' @param backend_store_uri URI for the backend store (e.g., `sqlite:///mlflow.db`,
#'   `postgresql://user:pass@host/db`). Cannot be combined with `file_store`.
#'   When neither is provided, a local SQLite database under `mlruns/` is used.
#' @export
mlflow_server <- function(file_store = "mlruns", default_artifact_root = NULL,
                          host = "127.0.0.1", port = 5000, workers = NULL, static_prefix = NULL,
                          serve_artifacts = FALSE, backend_store_uri = NULL) {
  if (!is.null(backend_store_uri) && !missing(file_store)) {
    stop(
      "Cannot specify both `file_store` and `backend_store_uri`. ",
      "Use `backend_store_uri` only.",
      call. = FALSE
    )
  }
  if (is.null(backend_store_uri)) {
    if (!missing(file_store)) {
      warning(
        "The `file_store` argument is deprecated. Use `backend_store_uri` instead ",
        "(e.g., `mlflow_server(backend_store_uri = \"sqlite:///mlflow.db\")`).",
        call. = FALSE
      )
      backend_store_uri <- fs::path_abs(file_store)
      if (.Platform$OS.type == "windows") backend_store_uri <- paste0("file://", backend_store_uri)
    } else {
      backing_dir <- fs::path_abs(file_store)
      if (!dir.exists(backing_dir)) {
        dir.create(backing_dir, recursive = TRUE, showWarnings = FALSE)
      }
      backend_store_uri <- paste0("sqlite:///", backing_dir, "/mlflow.db")
      if (is.null(default_artifact_root)) {
        default_artifact_root <- backing_dir
      }
    }
  }

  args <- mlflow_cli_param(list(), "--port", port) %>%
    mlflow_cli_param("--backend-store-uri", backend_store_uri) %>%
    mlflow_cli_param("--default-artifact-root", default_artifact_root) %>%
    mlflow_cli_param("--host", host) %>%
    mlflow_cli_param("--port", port) %>%
    mlflow_cli_param("--static-prefix", static_prefix) %>%
    append(if (serve_artifacts) "--serve-artifacts" else "--no-serve-artifacts")

  if (.Platform$OS.type != "windows") {
    workers <- workers %||% 4
    args <- args %>% mlflow_cli_param("--workers", workers)
  }

  mlflow_verbose_message("MLflow starting: http://", host, ":", port)

  handle <- do.call(
    "mlflow_cli",
    c(
      "server",
      args,
      list(
        background = getOption("mlflow.ui.background", TRUE),
        client = NULL
      )
    )
  )

  server_url <- getOption("mlflow.ui", paste(host, port, sep = ":"))
  new_mlflow_server(server_url, handle, file_store = file_store)
}

new_mlflow_server <- function(server_url, handle, ...) {
  ms <- structure(
    list(
      server_url = if (startsWith(server_url, "http")) server_url else paste0("http://", server_url),
      handle = handle,
      ...
    ),
    class = "mlflow_server"
  )
  ms
}

mlflow_validate_server <- function(client) {
  wait_for(
    function() mlflow_rest(
      "experiments",
      "search",
      client = client,
      verb = "POST",
      data = list(
        max_results = 1
      )
    ),
    getOption("mlflow.connect.wait", 10),
    getOption("mlflow.connect.sleep", 1)
  )
}

mlflow_register_local_server <- function(tracking_uri, local_server) {
  .globals$url_mapping[[tracking_uri]] <- local_server
}

mlflow_local_server <- function(tracking_uri) {
  .globals$url_mapping[[tracking_uri]]
}
