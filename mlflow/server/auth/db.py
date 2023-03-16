from typing import List
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash
from .permissions import NO_PERMISSIONS


db = SQLAlchemy()


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
    experiment_id = db.Column(db.String(255), unique=True, nullable=False)
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


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        if User.query.filter_by(name="user_a").first() is None:
            db.session.add(User(name="user_a", password=generate_password_hash("pass_a")))
        if User.query.filter_by(name="user_b").first() is None:
            db.session.add(User(name="user_b", password=generate_password_hash("pass_b")))
        db.session.commit()


def get_experiment_permission(experiment_id: str, user_id: int) -> ExperimentPermission:
    return ExperimentPermission.query.filter_by(
        experiment_id=experiment_id, user_id=user_id
    ).first()


def get_readable_experiments(user_id: int) -> List[ExperimentPermission]:
    return {e.experiment_id for e in ExperimentPermission.query.filter_by(user_id=user_id).all()}


def get_unreadable_experiments(user_id: int) -> List[ExperimentPermission]:
    return {
        e.experiment_id
        for e in ExperimentPermission.query.filter_by(
            user_id=user_id, permission=NO_PERMISSIONS.name
        ).all()
    }


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


def list_users():
    return User.query.all()


def create_user(name: str, password: str) -> None:
    db.session.add(User(name=name, password=generate_password_hash(password)))
    db.session.commit()


def get_user(name: str) -> User:
    return User.query.filter_by(name=name).one_or_404()
