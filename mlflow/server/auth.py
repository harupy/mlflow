"""
Provides a minimum authentication and authorization layer for MLflow.
This module is intended to be used as a plugin for the MLflow server.

Provides:

- Endpoints to manage users and permissions for MLflow resources.
- Pre/post hooks to authenticate and authorize requests to MLflow resources.
"""

import os
from typing import List
from abc import ABC, abstractmethod
import requests
import logging
import functools

from mlflow import MlflowException
from mlflow.protos.databricks_pb2 import INVALID_PARAMETER_VALUE
from flask import request, jsonify, Response, make_response, redirect
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

LOGGER = logging.getLogger(__name__)

db = SQLAlchemy()


class ROUTES:
    CREATE_EXPERIMENT = "/mlflow/experiments/create"
    GET_EXPERIMENT = "/mlflow/experiments/get"
    UPDATE_EXPERIMENT = "/mlflow/experiments/update"
    DELETE_EXPERIMENT = "/mlflow/experiments/delete"
    SEARCH_EXPERIMENTS = "/mlflow/experiments/search"
    CREATE_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/create"
    READ_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/read"
    UPDATE_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/update"
    DELETE_EXPERIMENT_PERMISSION = "/mlflow/experiments/permissions/delete"
    USERS = "/users"
    SIGNUP = "/signup"


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), unique=True)
    password = db.Column(db.String(255))
    is_admin = db.Column(db.Boolean, default=False)
    experiment_permissions = db.relationship("ExperimentPermission", backref="users")
    registered_models_permissions = db.relationship("RegisteredModelPermission", backref="users")


class ExperimentPermission(db.Model):
    __tablename__ = "experiment_permissions"
    id = db.Column(db.Integer(), primary_key=True)
    experiment_id = db.Column(db.Integer(), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    permission = db.Column(db.String(255))

    def to_json(self):
        return {
            "experiment_id": self.experiment_id,
            "user_id": self.user_id,
            "permission": self.permission,
        }


class RegisteredModelPermission(db.Model):
    __tablename__ = "registered_models_permissions"
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    permission = db.Column(db.String(255))


# Database to manage users and permissions for MLflow experiments and registered models
SQLALCHEMY_DATABASE_URI = "sqlite:///mlflow-auth.db"


def init_app(app):
    # Initialize the database
    app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Test users
        if User.query.filter_by(name="admin").first() is None:
            db.session.add(
                User(
                    name="admin",
                    password=generate_password_hash(os.environ["ADMIN_PASSWORD"]),
                    is_admin=True,
                )
            )
        if User.query.filter_by(name="user_a").first() is None:
            db.session.add(User(name="user_a", password=generate_password_hash("pass_a")))
        if User.query.filter_by(name="user_b").first() is None:
            db.session.add(User(name="user_b", password=generate_password_hash("pass_b")))
        db.session.commit()

    # Add endpoints for permissions management
    app.add_url_rule(
        ROUTES.CREATE_EXPERIMENT_PERMISSION,
        "create_experiment_permission",
        create_experiment_permission_handler,
        methods=["POST"],
    )
    app.add_url_rule(
        ROUTES.READ_EXPERIMENT_PERMISSION,
        "get_experiment_permission",
        get_experiment_permission_handler,
        methods=["GET"],
    )
    app.add_url_rule(
        ROUTES.UPDATE_EXPERIMENT_PERMISSION,
        "update_experiment_permission",
        update_experiment_permission_handler,
        methods=["POST"],
    )
    app.add_url_rule(
        ROUTES.DELETE_EXPERIMENT_PERMISSION,
        "delete_experiment_permission",
        delete_experiment_permission_handler,
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
        create_user_handler.__name__,
        create_user_handler,
        methods=["POST"],
    )
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


def create_user_handler():
    if request.headers.get("Content-Type") == "application/x-www-form-urlencoded":
        username = request.form["username"]
        password = request.form["password"]
    elif request.headers.get("Content-Type") == "application/json":
        username = request.json["username"]
        password = request.json["password"]
    else:
        return make_response("Invalid content type", 400)
    create_user(username, password)
    return redirect("/")


def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if request.authorization is None:
            return make_basic_auth_response()

        return f(*args, **kwargs)

    return decorated


def require_admin(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        username = request.authorization.username
        if username != "admin":
            return make_401_response("Permission denied")

        password = request.authorization.password
        if not verify_user(username, password):
            return make_401_response("Permission denied")

        return f(*args, **kwargs)

    return decorated


@require_auth
@require_admin
def list_users():
    return jsonify([u.name for u in User.query.all()])


def verify_user(name: str, password: str) -> bool:
    return check_password_hash(get_user(name).password, password)


def create_user(name: str, password: str) -> None:
    db.session.add(User(name=name, password=generate_password_hash(password)))
    db.session.commit()


def get_user(name: str) -> User:
    return User.query.filter_by(name=name).one_or_404()


def get_experiment_permission(experiment_id: str, user_id: int) -> ExperimentPermission:
    return ExperimentPermission.query.filter_by(
        experiment_id=experiment_id, user_id=user_id
    ).first()


def get_readable_experiments(user_id: int) -> List[ExperimentPermission]:
    return [e.experiment_id for e in ExperimentPermission.query.filter_by(user_id=user_id).all()]


def create_experiment_permission(experiment_id: str, user_id: int, permission: str) -> None:
    db.session.add(
        ExperimentPermission(experiment_id=experiment_id, user_id=user_id, permission=permission)
    )
    db.session.commit()


def update_experiment_permission(experiment_id: str, user_id: int, permission: str) -> None:
    perm = get_experiment_permission(experiment_id, user_id)
    perm.permission = permission
    db.session.commit()


def delete_experiment_permission(experiment_id: str, user_id: int) -> None:
    perm = get_experiment_permission(experiment_id, user_id)
    db.session.delete(perm)
    db.session.commit()


def get_experiment_permission_handler():
    experiment_id = get_experiment_id()
    user_id = get_user(request.authorization.username).id
    permission = get_experiment_permission(experiment_id, user_id)
    if permission is None:
        return make_forbidden_response()
    return jsonify(**permission.to_json()), 200


def create_experiment_permission_handler():
    experiment_id = get_experiment_id()
    user_id = get_user(request.authorization.username).id
    permission = request.json["permission"]
    create_experiment_permission(experiment_id, user_id, permission)
    return jsonify(), 200


def update_experiment_permission_handler():
    experiment_id = get_experiment_id()
    user_id = get_user(request.authorization.username).id
    permission = request.json["permission"]
    update_experiment_permission(experiment_id, user_id, permission)
    return jsonify(), 200


def delete_experiment_permission_handler():
    experiment_id = get_experiment_id()
    user_id = get_user(request.authorization.username).id
    delete_experiment_permission(experiment_id, user_id)
    return jsonify(), 200


class AbstractPermission(ABC):
    NAME = ""

    @abstractmethod
    def can_read(self) -> bool:
        pass

    @abstractmethod
    def can_update(self) -> bool:
        pass

    @abstractmethod
    def can_delete(self) -> bool:
        pass

    @abstractmethod
    def can_manage(self) -> bool:
        pass


class Read(AbstractPermission):
    NAME = "READ"

    def can_read(self) -> bool:
        return True

    def can_update(self) -> bool:
        return False

    def can_delete(self) -> bool:
        return False

    def can_manage(self) -> bool:
        pass


class Edit(AbstractPermission):
    NAME = "EDIT"

    def can_read(self) -> bool:
        return True

    def can_update(self) -> bool:
        return True

    def can_delete(self) -> bool:
        return False

    def can_manage(self) -> bool:
        return False


class Manage(AbstractPermission):
    NAME = "MANAGE"

    def can_read(self) -> bool:
        return True

    def can_update(self) -> bool:
        return True

    def can_delete(self) -> bool:
        return True

    def can_manage(self) -> bool:
        return True


def get_perm(permission: str) -> AbstractPermission:
    return {
        Read.NAME: Read(),
        Edit.NAME: Edit(),
        Manage.NAME: Manage(),
    }[permission]


def make_forbidden_response():
    res = make_response("Permission denied")
    res.status_code = 403
    return res


def is_authenticated():
    auth = request.authorization
    return verify_user(auth.username, auth.password)


def make_basic_auth_response():
    res = make_response()
    res.status_code = 401
    res.headers["WWW-Authenticate"] = 'Basic realm="mlflow"'
    return res


def make_401_response(msg):
    res = make_response(msg)
    res.status_code = 401
    return res


def get_experiment_id() -> str:
    if request.method == "GET":
        return request.args["experiment_id"]
    elif request.method == "POST":
        return request.json["experiment_id"]
    else:
        raise NotImplementedError()


# Validators
def add_mange_permission_to_experiment(resp: Response):
    user = get_user(request.authorization.username)
    create_experiment_permission(resp.json["experiment_id"], user.id, Manage.NAME)
    return resp


def filter_searched_experiments(resp: Response):
    user = get_user(request.authorization.username)
    experiments = resp.json["experiments"]
    filtered_experiments = []
    readable_experiments = set(get_readable_experiments(user.id))
    for experiment in experiments:
        if experiment["experiment_id"] in readable_experiments:
            filtered_experiments.append(experiment)
    new_data = {
        **resp.json,
        "experiments": filtered_experiments,
    }
    resp.set_data(resp.json_module.dumps(new_data))
    return resp


def validate_can_read_experiment():
    experiment_id = get_experiment_id()
    user = get_user(request.authorization.username)
    perm = get_experiment_permission(experiment_id, user.id)
    if perm is None or not get_perm(perm.permission).can_read():
        return make_forbidden_response()


def validate_can_update_experiment():
    experiment_id = get_experiment_id()
    user = get_user(request.authorization.username)
    perm = get_experiment_permission(experiment_id, user.id)
    if perm is None or not get_perm(perm.permission).can_update():
        return make_forbidden_response()


def validate_can_delete_experiment():
    experiment_id = get_experiment_id()
    user = get_user(request.authorization.username)
    perm = get_experiment_permission(experiment_id, user.id)
    if perm is None or not get_perm(perm.permission).can_delete():
        return make_forbidden_response()


def validate_can_manage_experiment():
    experiment_id = get_experiment_id()
    user = get_user(request.authorization.username)
    perm = get_experiment_permission(experiment_id, user.id)
    if perm is None or not get_perm(perm.permission).can_manage():
        return make_forbidden_response()


def before_request():
    LOGGER.info("before_request: %s %s %s", request.method, request.path, request.authorization)
    if any(request.path.startswith(r) for r in [ROUTES.SIGNUP, "/static-files"]):
        return

    if request.authorization is None:
        return make_basic_auth_response()

    validators = {
        # Experiments
        ROUTES.GET_EXPERIMENT: validate_can_read_experiment,
        ROUTES.UPDATE_EXPERIMENT: validate_can_update_experiment,
        ROUTES.DELETE_EXPERIMENT: validate_can_delete_experiment,
        # Registered Models
        # ...,
        # Permissions
        ROUTES.READ_EXPERIMENT_PERMISSION: validate_can_manage_experiment,
        ROUTES.CREATE_EXPERIMENT_PERMISSION: validate_can_manage_experiment,
        ROUTES.UPDATE_EXPERIMENT_PERMISSION: validate_can_manage_experiment,
        ROUTES.DELETE_EXPERIMENT_PERMISSION: validate_can_manage_experiment,
    }

    # Call a validator
    for route, validator in validators.items():
        if request.path.endswith(route):
            return validator()


def after_request(resp):
    LOGGER.info("after_request: %s %s %s", request.method, request.path, request.authorization)
    if resp.status_code == 200:
        routes = {
            ROUTES.CREATE_EXPERIMENT: add_mange_permission_to_experiment,
            ROUTES.SEARCH_EXPERIMENTS: filter_searched_experiments,
        }
        for route, handler in routes.items():
            if request.path.endswith(route):
                resp = handler(resp)
                break

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

    def _validate_permission(self, permission: str):
        if permission not in [Read.NAME, Edit.NAME, Manage.NAME]:
            raise MlflowException("Invalid permission", error_code=INVALID_PARAMETER_VALUE)

    def get_experiment_permission(self, experiment_id: str, username: str):
        return self._request(
            ROUTES.READ_EXPERIMENT_PERMISSION,
            "GET",
            params={"experiment_id": experiment_id, "username": username},
        )

    def create_experiment_permission(self, experiment_id: str, username: str, permission: str):
        self._validate_permission(permission)
        return self._request(
            ROUTES.CREATE_EXPERIMENT_PERMISSION,
            "POST",
            json={"experiment_id": experiment_id, "username": username, "permission": permission},
        )

    def update_experiment_permission(self, experiment_id: str, username: str, permission: str):
        self._validate_permission(permission)
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
