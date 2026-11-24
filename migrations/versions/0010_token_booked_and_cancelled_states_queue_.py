"""token booked and cancelled states, queue order

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-24 16:24:37.600284

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_STATUSES = ('waiting', 'in_consultation', 'done')
NEW_STATUSES = ('booked', 'waiting', 'in_consultation', 'done', 'cancelled')


def status_type(values):
    return sa.Enum(*values, name='token_status', native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    """
    Tokens for appointments (Module 5, step 4):
      - two new columns for the queue order: scheduled_at (slot time) and priority
      - two new statuses: booked (patient not here yet) and cancelled.
        Alembic can't see new Enum values, so that part is written by hand (LEARN.md 16.8).
    """
    with op.batch_alter_table('tokens', schema=None, recreate='always') as batch_op:
        batch_op.add_column(sa.Column('scheduled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('priority', sa.Integer(), server_default='0', nullable=False))
        batch_op.alter_column('status', existing_type=status_type(OLD_STATUSES), type_=status_type(NEW_STATUSES),
                              existing_nullable=False)


def downgrade() -> None:
    # Booked / cancelled tokens can't exist in the old rule: count them as done first.
    op.execute("UPDATE tokens SET status = 'done' WHERE status IN ('booked', 'cancelled')")
    with op.batch_alter_table('tokens', schema=None, recreate='always') as batch_op:
        batch_op.alter_column('status', existing_type=status_type(NEW_STATUSES), type_=status_type(OLD_STATUSES),
                              existing_nullable=False)
        batch_op.drop_column('priority')
        batch_op.drop_column('scheduled_at')
