"""
Provides a minimum authentication and authorization layer for MLflow.
This module is intended to be used as a plugin for the MLflow server.

Provides:

- Endpoints to manage users and permissions for MLflow resources.
- Pre/post hooks to authenticate and authorize requests to MLflow resources.
"""

import requests
import logging
import functools
import configparser
import base64
import json
from pathlib import Path
from typing import NamedTuple

from flask import request, jsonify, Response, make_response, redirect

from mlflow.server import app as app
from mlflow.server.handlers import (
    _get_tracking_store,
    _get_request_message,
    get_endpoints,
    message_to_json,
)
from mlflow.protos.service_pb2 import (
    CreateExperiment,
    GetExperiment,
    GetRun,
    SearchRuns,
    ListArtifacts,
    GetMetricHistory,
    CreateRun,
    UpdateRun,
    LogMetric,
    LogParam,
    SetTag,
    SearchExperiments,
    DeleteExperiment,
    RestoreExperiment,
    RestoreRun,
    DeleteRun,
    UpdateExperiment,
    LogBatch,
    DeleteTag,
    SetExperimentTag,
    GetExperimentByName,
    LogModel,
)

from .permissions import (
    MANAGE,
    get_permission,
    validate_permission,
)
from . import db

LOGGER = logging.getLogger(__name__)


class AppConfig(NamedTuple):
    default_permission: str
    database_uri: str


def read_app_config() -> AppConfig:
    creds_path = Path("basic_auth.ini").resolve()
    config = configparser.ConfigParser()
    config.read(str(creds_path))
    return AppConfig(
        default_permission=config["mlflow"]["default_permission"],
        database_uri=config["mlflow"]["database_uri"],
    )


APP_CONFIG = read_app_config()


class ROUTES:
    CREATE_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/create"
    READ_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/read"
    UPDATE_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/update"
    DELETE_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/delete"
    USERS = "/users"
    SIGNUP = "/signup"

    def to_json(self):
        return {
            "experiment_id": self.experiment_id,
            "user_id": self.user_id,
            "permission": self.permission,
        }


def init_app(app):
    LOGGER.info("Database URI: %s", APP_CONFIG.database_uri)
    app.config["SQLALCHEMY_DATABASE_URI"] = APP_CONFIG.database_uri

    db.init_db(app)

    # Add endpoints for permissions management
    app.add_url_rule(
        ROUTES.CREATE_EXPERIMENT_PERMISSION,
        create_experiment_permission.__name__,
        create_experiment_permission,
        methods=["POST"],
    )
    app.add_url_rule(
        ROUTES.READ_EXPERIMENT_PERMISSION,
        "get_experiment_permission",
        get_experiment_permission,
        methods=["GET"],
    )
    app.add_url_rule(
        ROUTES.UPDATE_EXPERIMENT_PERMISSION,
        "update_experiment_permission",
        update_experiment_permission,
        methods=["POST"],
    )
    app.add_url_rule(
        ROUTES.DELETE_EXPERIMENT_PERMISSION,
        "delete_experiment_permission",
        delete_experiment_permission,
        methods=["DELETE"],
    )
    app.add_url_rule(
        ROUTES.SIGNUP,
        signup.__name__,
        signup,
        methods=["GET"],
    )
    app.add_url_rule(
        ROUTES.USERS,
        list_users.__name__,
        list_users,
        methods=["GET"],
    )
    app.add_url_rule(
        ROUTES.USERS,
        create_user.__name__,
        create_user,
        methods=["POST"],
    )

    # Register request hooks
    app.before_request(before_request)
    app.after_request(after_request)


def signup():
    return """
<form action="/users" method="post">
  Username:
  <br>
  <input type=text name=username>
  <br>

  Password:
  <br>
  <input type=password name=password>
  <br>

  <br>
  <input type="submit" value="Signup">
</form>
"""


def create_user():
    if request.headers.get("Content-Type") == "application/x-www-form-urlencoded":
        username = request.form["username"]
        password = request.form["password"]
    elif request.headers.get("Content-Type") == "application/json":
        username = request.json["username"]
        password = request.json["password"]
    else:
        return make_response("Invalid content type", 400)
    db.create_user(username, password)
    return redirect("/")


def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if request.authorization is None:
            return make_basic_auth_response()

        return f(*args, **kwargs)

    return decorated


# def require_admin(f):
#     @functools.wraps(f)
#     def decorated(*args, **kwargs):
#         username = request.authorization.username
#         if username != "admin":
#             return make_401_response("Permission denied")

#         password = request.authorization.password
#         if not verify_user(username, password):
#             return make_401_response("Permission denied")

#         return f(*args, **kwargs)

#     return decorated


@require_auth
def list_users():
    return jsonify([user.name for user in db.list_users()])


def get_experiment_permission():
    experiment_id = get_experiment_id()
    user_id = db.get_user(request.authorization.username).id
    permission = db.get_experiment_permission(experiment_id, user_id)
    if permission is None:
        return make_forbidden_response()
    return jsonify(**permission.to_json()), 200


def create_experiment_permission():
    experiment_id = get_experiment_id()
    user_id = db.get_user(request.authorization.username).id
    permission = request.json["permission"]
    db.create_experiment_permission(experiment_id, user_id, permission)
    return jsonify(), 200


def update_experiment_permission():
    experiment_id = get_experiment_id()
    user_id = db.get_user(request.authorization.username).id
    permission = request.json["permission"]
    db.update_experiment_permission(experiment_id, user_id, permission)
    return jsonify(), 200


def delete_experiment_permission():
    experiment_id = get_experiment_id()
    user_id = db.get_user(request.authorization.username).id
    db.delete_experiment_permission(experiment_id, user_id)
    return jsonify(), 200


def make_forbidden_response() -> Response:
    res = make_response("Permission denied")
    res.status_code = 403
    return res


def make_basic_auth_response() -> Response:
    res = make_response()
    res.status_code = 401
    res.headers["WWW-Authenticate"] = 'Basic realm="mlflow"'
    return res


def get_experiment_id() -> str:
    if request.method == "GET":
        return request.args["experiment_id"]
    elif request.method == "POST":
        return request.json["experiment_id"]
    else:
        raise NotImplementedError()


def get_run_id() -> str:
    if request.method == "GET":
        return request.args["run_id"]
    elif request.method == "POST":
        return request.json["run_id"]
    else:
        raise NotImplementedError()


def add_manage_permission_to_experiment(response: Response):
    user = db.get_user(request.authorization.username)
    db.create_experiment_permission(str(response.json["experiment_id"]), user.id, MANAGE.name)
    return response


def jsonify_experiments(experiment_entities):
    response = SearchExperiments.Response(experiments=[e.to_proto() for e in experiment_entities])
    return message_to_json(response)["experiments"]


def select_readable_experiments(response: Response):
    user = db.get_user(request.authorization.username)
    max_results = request.json["max_results"]
    experiments = response.json["experiments"]
    unreadable_experiments = set(db.get_unreadable_experiments(user.id))
    readable_experiments = [
        exp for exp in experiments if exp["experiment_id"] not in unreadable_experiments
    ]

    request_message = _get_request_message(SearchExperiments())
    next_page_token = response.json.get("next_page_token")
    # If we already have enough experiments or this is the last page, we don't need to refetch
    while len(readable_experiments) < max_results or next_page_token:
        batch = _get_tracking_store().search_experiments(
            view_type=request_message.view_type,
            max_results=request_message.max_results,
            order_by=request_message.order_by,
            filter_string=request_message.filter,
            page_token=next_page_token,
        )
        experiment_id_to_index = {}
        readable_experiments_in_batch = []
        for index, exp in enumerate(batch.experiments):
            if exp.experiment_id not in unreadable_experiments:
                experiment_id_to_index[exp.experiment_id] = index
                readable_experiments_in_batch.append(exp)

        # If we truncate the experiments in the batch, we need to adjust the next page token
        diff = max_results - len(readable_experiments)
        if len(readable_experiments_in_batch) > diff:
            truncated = readable_experiments_in_batch[:diff]
            readable_experiments += jsonify_experiments(truncated)
            offset_in_batch = experiment_id_to_index[truncated[-1].experiment_id] + 1
            # Adjust the next page token
            offset_to_batch = json.loads(base64.b64decode(next_page_token))["offset"]
            offset = offset_to_batch + offset_in_batch
            next_page_token = base64.b64encode(json.dumps({"offset": offset}).encode())
            # If we reach here, `readable_experiments` should have `max_results` experiments
            break

        readable_experiments += jsonify_experiments(readable_experiments_in_batch)
        next_page_token = batch.token

    new_data = {
        **response.json,
        "experiments": readable_experiments,
        "next_page_token": next_page_token,
    }
    response.set_data(response.json_module.dumps(new_data))
    return response


def get_permission_from_experiment_id():
    experiment_id = get_experiment_id()
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    return perm.permission if perm else APP_CONFIG.default_permission


def get_permission_from_run_id():
    run_id = get_run_id()
    user = db.get_user(request.authorization.username)
    perm = db.get_run_permission(run_id, user.id)
    return perm.permission if perm else APP_CONFIG.default_permission


def validate_can_read_experiment():
    experiment_id = get_experiment_id()
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    perm = perm.permission if perm else APP_CONFIG.default_permission
    if get_permission(perm).can_read:
        return make_forbidden_response()


def validate_can_update_experiment():
    experiment_id = get_experiment_id()
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    perm = perm.permission if perm else APP_CONFIG.default_permission
    if get_permission(perm).can_update:
        return make_forbidden_response()


def validate_can_delete_experiment():
    experiment_id = get_experiment_id()
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    perm = perm.permission if perm else APP_CONFIG.default_permission
    if get_permission(perm).can_delete:
        return make_forbidden_response()


def validate_can_manage_experiment():
    experiment_id = get_experiment_id()
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    perm = perm.permission if perm else APP_CONFIG.default_permission
    if get_permission(perm).can_manage:
        return make_forbidden_response()


def validate_can_read_run():
    run_id = get_run_id()
    run = _get_tracking_store().get_run(run_id)
    experiment_id = run.info.experiment_id
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    perm = perm.permission if perm else APP_CONFIG.default_permission
    if get_permission(perm).can_read:
        return make_forbidden_response()


def validate_can_update_run():
    run_id = get_run_id()
    run = _get_tracking_store().get_run(run_id)
    experiment_id = run.info.experiment_id
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    perm = perm.permission if perm else APP_CONFIG.default_permission
    if get_permission(perm).can_update:
        return make_forbidden_response()


def validate_can_delete_run():
    run_id = get_run_id()
    run = _get_tracking_store().get_run(run_id)
    experiment_id = run.info.experiment_id
    user = db.get_user(request.authorization.username)
    perm = db.get_experiment_permission(experiment_id, user.id)
    perm = perm.permission if perm else APP_CONFIG.default_permission
    if get_permission(perm).can_update:
        return make_forbidden_response()


def get_before_request_handler(request_class):
    return {
        # Routes for experiments
        GetExperiment: validate_can_read_experiment,
        GetExperimentByName: validate_can_read_experiment,
        UpdateExperiment: validate_can_update_experiment,
        DeleteExperiment: validate_can_delete_experiment,
        RestoreExperiment: validate_can_delete_experiment,
        SetExperimentTag: validate_can_update_experiment,
        # Routes for runs
        CreateRun: validate_can_update_experiment,
        GetRun: validate_can_read_run,
        UpdateRun: validate_can_update_run,
        DeleteRun: validate_can_delete_run,
        RestoreRun: validate_can_delete_run,
        ListArtifacts: validate_can_read_run,
        GetMetricHistory: validate_can_read_run,
        LogMetric: validate_can_update_run,
        LogParam: validate_can_update_run,
        SetTag: validate_can_update_run,
        DeleteTag: validate_can_update_run,
        LogModel: validate_can_update_run,
        LogBatch: validate_can_update_run,
    }.get(request_class)


def get_after_request_handler(request_class):
    return {
        CreateExperiment: add_manage_permission_to_experiment,
        SearchExperiments: filter_out_unreadable_experiments,
    }.get(request_class)


BEFORE_REQUEST = {
    (http_path, method): handler
    for http_path, handler, method in get_endpoints(get_before_request_handler)
}
BEFORE_REQUEST.update(
    {
        (ROUTES.READ_EXPERIMENT_PERMISSION, "GET"): validate_can_manage_experiment,
        (ROUTES.CREATE_EXPERIMENT_PERMISSION, "PUT"): validate_can_manage_experiment,
        (ROUTES.UPDATE_EXPERIMENT_PERMISSION, "POST"): validate_can_manage_experiment,
        (ROUTES.DELETE_EXPERIMENT_PERMISSION, "DELETE"): validate_can_manage_experiment,
    }
)

AFTER_REQUEST = {
    (http_path, method): handler
    for http_path, handler, method in get_endpoints(get_after_request_handler)
}


def before_request():
    LOGGER.info("before_request: %s %s %s", request.method, request.path, request.authorization)
    if any(request.path.startswith(r) for r in [ROUTES.SIGNUP, "/static-files"]):
        return

    if request.authorization is None:
        return make_basic_auth_response()

    if f := BEFORE_REQUEST.get((request.path, request.method)):
        LOGGER.info("Calling validator: %s", f.__name__)
        f()


def after_request(resp):
    LOGGER.info("after_request: %s %s %s", request.method, request.path, request.authorization)
    if resp.status_code == 200:
        if f := AFTER_REQUEST.get((request.path, request.method)):
            LOGGER.info("Calling %s", f.__name__)
            resp = f(resp)
    return resp


class AuthClient:
    def __init__(self, url: str, username: str, password: str):
        self.url = url
        self.username = username
        self.password = password

    def _request(self, endpoint, method, **kwargs):
        resp = requests.request(
            method, f"{self.url}{endpoint}", auth=(self.username, self.password), **kwargs
        )
        resp.raise_for_status()
        return resp.json()

    def get_experiment_permission(self, experiment_id: str, username: str):
        return self._request(
            ROUTES.READ_EXPERIMENT_PERMISSION,
            "GET",
            params={"experiment_id": experiment_id, "username": username},
        )

    def create_experiment_permission(self, experiment_id: str, username: str, permission: str):
        validate_permission(permission)
        return self._request(
            ROUTES.CREATE_EXPERIMENT_PERMISSION,
            "POST",
            json={"experiment_id": experiment_id, "username": username, "permission": permission},
        )

    def update_experiment_permission(self, experiment_id: str, username: str, permission: str):
        validate_permission(permission)
        return self._request(
            ROUTES.UPDATE_EXPERIMENT_PERMISSION,
            "POST",
            json={"experiment_id": experiment_id, "username": username, "permission": permission},
        )

    def delete_experiment_permission(self, experiment_id: str, username: str):
        return self._request(
            ROUTES.DELETE_EXPERIMENT_PERMISSION.format(experiment_id=experiment_id),
            "DELETE",
            json={"experiment_id": experiment_id, "username": username},
        )


init_app(app)
