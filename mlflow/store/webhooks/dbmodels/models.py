import json
from enum import Enum

from sqlalchemy import BigInteger, Column, Index, String, Text

from mlflow.entities.model_registry.webhook import Webhook
from mlflow.store.db.base_sql_model import Base
from mlflow.utils.time import get_current_time_millis


class WebhookStatus(Enum):
    """Webhook status enumeration."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISABLED = "DISABLED"


class SqlModelRegistryWebhook(Base):
    """
    Database model for storing webhook configurations.

    This model corresponds to the model_registry_webhooks table defined in the
    migration script and supports Phase 1 of the webhook implementation.
    """

    __tablename__ = "model_registry_webhooks"

    # Primary key - UUID string
    id = Column(String(36), primary_key=True, nullable=False)

    # Webhook name - must be unique
    name = Column(String(255), nullable=False, unique=True)

    # Optional description
    description = Column(Text, nullable=True)

    # Webhook endpoint URL
    url = Column(String(2048), nullable=False)

    # JSON array of event types that trigger this webhook
    events = Column(Text, nullable=False)

    # Optional secret for HMAC signature verification
    secret = Column(String(255), nullable=True)

    # Webhook status
    status = Column(String(20), nullable=False, default=WebhookStatus.ACTIVE.value)

    # Timestamps in milliseconds
    created_at = Column(BigInteger, nullable=False, default=get_current_time_millis)
    updated_at = Column(BigInteger, nullable=False, default=get_current_time_millis)

    # Add indexes
    __table_args__ = (
        Index("unique_webhook_name", "name", unique=True),
        Index("idx_model_registry_webhooks_status", "status"),
    )

    def __repr__(self):
        return (
            f"<SqlModelRegistryWebhook("
            f"id={self.id}, "
            f"name={self.name}, "
            f"url={self.url}, "
            f"status={self.status}, "
            f"events={self.events[:50]}..."
            f")>"
        )

    def get_events_list(self) -> list[str]:
        """
        Parse the JSON events string into a list of event types.

        Returns:
            List of event type strings
        """
        try:
            return json.loads(self.events) if self.events else []
        except json.JSONDecodeError:
            return []

    def set_events_list(self, events: list[str]) -> None:
        """
        Set the events list as a JSON string.

        Args:
            events: List of event type strings to set
        """
        self.events = json.dumps(events) if events else "[]"

    def to_mlflow_entity(self) -> Webhook:
        return Webhook(
            id=self.id,
            name=self.name,
            description=self.description,
            url=self.url,
            events=self.get_events_list(),
            status=self.status,
            secret=self.secret,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
