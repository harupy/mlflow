"""add model registry webhooks table

Revision ID: ae3be8a5b9df
Revises: cbc13b556ace
Create Date: 2025-01-05 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ae3be8a5b9df"
down_revision = "cbc13b556ace"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_registry_webhooks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("events", sa.Text(), nullable=False),  # JSON array of event types
        sa.Column("secret", sa.String(length=255), nullable=True),  # For HMAC signature
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="model_registry_webhooks_pk"),
    )

    # Create unique index on webhook name
    op.create_index(
        "unique_webhook_name",
        "model_registry_webhooks",
        ["name"],
        unique=True,
    )

    # Create index on status for faster filtering
    op.create_index(
        "idx_model_registry_webhooks_status",
        "model_registry_webhooks",
        ["status"],
        unique=False,
    )


def downgrade():
    """
    Remove the model_registry_webhooks table.
    """
    # Drop indexes first
    op.drop_index("idx_model_registry_webhooks_status", table_name="model_registry_webhooks")
    op.drop_index("unique_webhook_name", table_name="model_registry_webhooks")

    # Drop the table
    op.drop_table("model_registry_webhooks")
