class Permission:
    def __init__(
        self,
        *,
        name: str,
        can_read: bool,
        can_update: bool,
        can_delete: bool,
        can_manage: bool,
    ):
        self.name = name
        self.can_read = can_read
        self.can_update = can_update
        self.can_delete = can_delete
        self.can_manage = can_manage


READ = Permission(
    name="READ",
    can_read=True,
    can_update=False,
    can_delete=False,
    can_manage=False,
)

EDIT = Permission(
    name="EDIT",
    can_read=True,
    can_update=True,
    can_delete=False,
    can_manage=False,
)

MANAGE = Permission(
    name="MANAGE",
    can_read=True,
    can_update=True,
    can_delete=True,
    can_manage=True,
)

NO_PERMISSIONS = Permission(
    name="NO_PERMISSIONS",
    can_read=False,
    can_update=False,
    can_delete=False,
    can_manage=False,
)


def get_permission(permission: str) -> Permission:
    return {
        READ.name: READ,
        EDIT.name: EDIT,
        MANAGE.name: MANAGE,
        NO_PERMISSIONS.name: NO_PERMISSIONS,
    }[permission]


def validate_permission(permission: str):
    if permission not in [READ.name, EDIT.name, MANAGE.name, NO_PERMISSIONS.name]:
        raise ValueError(
            f"Invalid permission: {permission}. Valid permissions are: {READ.name}, {EDIT.name}, {MANAGE.name}, {NO_PERMISSIONS.name}"
        )
