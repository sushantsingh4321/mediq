"""remove the receptionist role

Patients now book for themselves, so there is no reception desk. Any
receptionist accounts become ADMIN accounts (so those people keep access to
call-backs, enquiries, beds and ambulances), then "receptionist" is taken out
of the users.role CHECK rule. Written by hand: Alembic can't see Enum changes
(LEARN.md 16.8).

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WITH_RECEPTION = ('patient', 'receptionist', 'doctor', 'admin', 'pharmacist')
WITHOUT = ('patient', 'doctor', 'admin', 'pharmacist')


def role_type(values):
    return sa.Enum(*values, name='user_role', native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    # 1. move the people first, so no row breaks the new rule
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'receptionist'")
    # 2. then the rule (SQLite: batch mode rebuilds the table; env.py keeps foreign keys safe)
    with op.batch_alter_table('users', recreate='always') as batch_op:
        batch_op.alter_column('role', existing_type=role_type(WITH_RECEPTION), type_=role_type(WITHOUT),
                              existing_nullable=False)


def downgrade() -> None:
    # The role is allowed again, but we can't tell which admins used to be
    # receptionists, so nobody is moved back.
    with op.batch_alter_table('users', recreate='always') as batch_op:
        batch_op.alter_column('role', existing_type=role_type(WITHOUT), type_=role_type(WITH_RECEPTION),
                              existing_nullable=False)
