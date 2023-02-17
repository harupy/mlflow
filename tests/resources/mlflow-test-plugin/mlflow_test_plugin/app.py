import logging

# This would be all that plugin author is required to import
from mlflow.server import app as custom_app
from flask import request

# Can do custom logging on either the app or logging itself
# but you'll possibly have to clear the existing handlers or there will be duplicate output
# See https://docs.python.org/3/howto/logging-cookbook.html

logging.basicConfig(level=logging.INFO)
app_logger = logging.getLogger(__name__)

# Configure the app
custom_app.config["MY_VAR"] = "config-var"


def is_logged_in():
    return True


def get_role(user):
    return {
        "admin": "admin",
        "haru": "reader",
        "weichen": "writer",
    }.get(user)


def is_authorized(path, role):
    return role in {
        "/api/2.0/mlflow/experiments/search": ["admin", "reader", "writer"],
        "/api/2.0/mlflow/experiments/create": ["admin", "writer"],
        "/api/2.0/mlflow/experiments/delete": ["admin", "writer"],
        "/api/2.0/mlflow/experiments/update": ["admin", "writer"],
        "/api/2.0/mlflow/experiments/get": ["admin", "reader", "writer"],
        # ...
    }.get(path, [])


@custom_app.before_request
def auth():
    """A custom before request handler.

    Can implement things such as authentication, special handling, etc.
    """
    app_logger.info("Request path: %s", request.path)
    app_logger.info("Request method: %s", request.method)
    app_logger.info("Request auth: %s", request.authorization)
    if not request.authorization:
        return "Unauthorized", 403

    app_logger.info("username: %s", request.authorization.username)
    app_logger.info("password: %s", request.authorization.password)

    role = get_role(request.authorization.username)
    app_logger.info("Role: %s", role)
    if not is_authorized(request.path, role):
        return "Unauthorized", 403
