"""v0.3 key policy (models/ip/expiry/spend limit) + audit log

Revision ID: 0003_v03
Revises: 0002_v02
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_v03'
down_revision = '0002_v02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('api_keys') as b:
        b.add_column(sa.Column('allowed_models', sa.Text(), nullable=False, server_default=''))
        b.add_column(sa.Column('ip_allowlist', sa.Text(), nullable=False, server_default=''))
        b.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('spend_limit_micro', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('spent_micro', sa.BigInteger(), nullable=False, server_default='0'))
    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('actor_type', sa.String(16), nullable=False),
        sa.Column('actor', sa.String(254), nullable=False),
        sa.Column('tenant_id', sa.String(32), nullable=True),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('target', sa.String(200), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('ip', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_created_at', 'audit_logs')
    op.drop_index('ix_audit_logs_tenant_id', 'audit_logs')
    op.drop_table('audit_logs')
    with op.batch_alter_table('api_keys') as b:
        for c in ('spent_micro', 'spend_limit_micro', 'expires_at', 'ip_allowlist', 'allowed_models'):
            b.drop_column(c)
