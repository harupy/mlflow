from enum import Enum
from typing import Any, Optional

from mlflow.entities.model_registry._model_registry_entity import _ModelRegistryEntity


class WebhookStatus:
    """Webhook status constants."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISABLED = "DISABLED"


class WebhookEventType(str, Enum):
    # Registered Model Events
    REGISTERED_MODEL_CREATED = "REGISTERED_MODEL_CREATED"

    # Model Version Events
    MODEL_VERSION_CREATED = "MODEL_VERSION_CREATED"
    MODEL_VERSION_TAG_SET = "MODEL_VERSION_TAG_SET"
    MODEL_VERSION_TAG_DELETED = "MODEL_VERSION_TAG_DELETED"

    # Model Alias Events
    MODEL_ALIAS_SET = "MODEL_ALIAS_SET"
    MODEL_ALIAS_DELETED = "MODEL_ALIAS_DELETED"


class Webhook(_ModelRegistryEntity):
    """
    MLflow entity for Model Registry Webhook.

    A webhook represents a configuration for receiving notifications
    about model registry events via HTTP POST requests.
    """

    def __init__(
        self,
        id: str,
        name: str,
        url: str,
        events: list[str],
        description: Optional[str] = None,
        status: str = WebhookStatus.ACTIVE,
        secret: Optional[str] = None,
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
    ):
        """
        Initialize a Webhook entity.

        Args:
            id: Unique webhook identifier
            name: Human-readable webhook name
            url: Webhook endpoint URL
            events: List of event types that trigger this webhook
            description: Optional webhook description
            status: Webhook status (ACTIVE, INACTIVE, or DISABLED)
            secret: Optional secret key for HMAC signature verification
            created_at: Creation timestamp in milliseconds since Unix epoch
            updated_at: Last update timestamp in milliseconds since Unix epoch
        """
        super().__init__()
        self._id = id
        self._name = name
        self._url = url
        self._events = events or []
        self._description = description
        self._status = status
        self._secret = secret
        self._created_at = created_at
        self._updated_at = updated_at

    @property
    def id(self) -> str:
        """String. Unique webhook identifier."""
        return self._id

    @property
    def name(self) -> str:
        """String. Human-readable webhook name."""
        return self._name

    @name.setter
    def name(self, new_name: str) -> None:
        self._name = new_name

    @property
    def url(self) -> str:
        """String. Webhook endpoint URL."""
        return self._url

    @url.setter
    def url(self, new_url: str) -> None:
        self._url = new_url

    @property
    def events(self) -> list[str]:
        """List[str]. Event types that trigger this webhook."""
        return self._events

    @events.setter
    def events(self, new_events: list[str]) -> None:
        self._events = new_events or []

    @property
    def description(self) -> Optional[str]:
        """Optional[str]. Webhook description."""
        return self._description

    @description.setter
    def description(self, new_description: Optional[str]) -> None:
        self._description = new_description

    @property
    def status(self) -> str:
        """String. Webhook status (ACTIVE, INACTIVE, or DISABLED)."""
        return self._status

    @status.setter
    def status(self, new_status: str) -> None:
        self._status = new_status

    @property
    def secret(self) -> Optional[str]:
        """Optional[str]. Secret key for HMAC signature verification."""
        return self._secret

    @secret.setter
    def secret(self, new_secret: Optional[str]) -> None:
        self._secret = new_secret

    @property
    def created_at(self) -> Optional[int]:
        """Optional[int]. Creation timestamp (milliseconds since Unix epoch)."""
        return self._created_at

    @property
    def updated_at(self) -> Optional[int]:
        """Optional[int]. Last update timestamp (milliseconds since Unix epoch)."""
        return self._updated_at

    @updated_at.setter
    def updated_at(self, new_updated_at: Optional[int]) -> None:
        self._updated_at = new_updated_at

    def is_active(self) -> bool:
        """Check if the webhook is active."""
        return self._status == WebhookStatus.ACTIVE

    def should_trigger_for_event(self, event_type: str) -> bool:
        """
        Check if this webhook should be triggered for the given event type.

        Args:
            event_type: The event type to check

        Returns:
            True if the webhook should be triggered, False otherwise
        """
        return self.is_active() and event_type in self._events

    @classmethod
    def _properties(cls):
        """Get the list of property names for this entity."""
        return sorted(cls._get_properties_helper())

    @classmethod
    def from_proto(cls, proto):
        """
        Create a Webhook entity from a protobuf message.

        Args:
            proto: Protobuf webhook message

        Returns:
            Webhook entity instance
        """
        from mlflow.protos.webhooks_pb2 import WebhookStatus as ProtoWebhookStatus

        # Convert protobuf enum to string status
        status = WebhookStatus.ACTIVE  # default
        if proto.status == ProtoWebhookStatus.ACTIVE:
            status = WebhookStatus.ACTIVE
        elif proto.status == ProtoWebhookStatus.INACTIVE:
            status = WebhookStatus.INACTIVE
        elif proto.status == ProtoWebhookStatus.DISABLED:
            status = WebhookStatus.DISABLED

        return cls(
            id=proto.id,
            name=proto.name,
            url=proto.url,
            events=list(proto.events),
            description=proto.description if proto.description else None,
            status=status,
            secret=proto.secret or None,
            created_at=proto.created_at if proto.created_at else None,
            updated_at=proto.updated_at if proto.updated_at else None,
        )

    def to_proto(self):
        """
        Convert this Webhook entity to a protobuf message.

        Returns:
            mlflow.protos.webhooks_pb2.Webhook: Protobuf webhook message
        """
        from mlflow.protos.webhooks_pb2 import Webhook as ProtoWebhook
        from mlflow.protos.webhooks_pb2 import WebhookStatus as ProtoWebhookStatus

        webhook = ProtoWebhook()
        webhook.id = self.id
        webhook.name = self.name
        webhook.url = self.url
        webhook.events.extend(self.events)

        if self.description is not None:
            webhook.description = self.description

        if self.secret is not None:
            webhook.secret = self.secret

        # Convert status from string to enum
        # The protobuf uses WebhookStatus enum with values: ACTIVE=1, INACTIVE=2, DISABLED=3
        if self.status == WebhookStatus.ACTIVE:
            webhook.status = ProtoWebhookStatus.ACTIVE
        elif self.status == WebhookStatus.INACTIVE:
            webhook.status = ProtoWebhookStatus.INACTIVE
        elif self.status == WebhookStatus.DISABLED:
            webhook.status = ProtoWebhookStatus.DISABLED

        if self.created_at is not None:
            webhook.created_at = self.created_at

        if self.updated_at is not None:
            webhook.updated_at = self.updated_at

        return webhook

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the webhook to a dictionary representation.

        Returns:
            Dictionary containing webhook data (excluding sensitive information)
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "events": self.events,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def __repr__(self) -> str:
        return (
            f"Webhook("
            f"id='{self.id}', "
            f"name='{self.name}', "
            f"url='{self.url}', "
            f"status='{self.status}', "
            f"events={self.events}"
            f")"
        )
