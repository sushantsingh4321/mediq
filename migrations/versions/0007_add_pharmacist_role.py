"""add the pharmacist role

The users.role column has a database rule (a CHECK constraint named
"user_role") listing the roles it accepts. Alembic can't spot a new value in
that list by itself, so this migration was written by hand.

SQLite can't change a CHECK rule in place, so batch mode copies the table
with the new rule, moves the rows across and swaps it in.

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def swap_check_rule(table: str, name: str, column: str, values) -> None:
    """
    PostgreSQL (and most databases): change a CHECK rule in place. Dropping and
    re-creating the whole table (what SQLite needs) isn't allowed there while
    other tables point at it with foreign keys.
    """
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, f"{column} IN ({', '.join(repr(v) for v in values)})")

OLD = ('patient', 'receptionist', 'doctor', 'admin')
NEW = OLD + ('pharmacist',)


def role_type(values):
    return sa.Enum(*values, name='user_role', native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    if not is_sqlite():
        return swap_check_rule("users", "user_role", "role", NEW)
    with op.batch_alter_table('users', recreate='always') as batch_op:
        batch_op.alter_column('role', existing_type=role_type(OLD), type_=role_type(NEW),
                              existing_nullable=False)


def downgrade() -> None:
    # Pharmacists become patients first, so the old rule can be put back.
    op.execute("UPDATE users SET role = 'patient' WHERE role = 'pharmacist'")
    if not is_sqlite():
        return swap_check_rule("users", "user_role", "role", OLD)
    with op.batch_alter_table('users', recreate='always') as batch_op:
        batch_op.alter_column('role', existing_type=role_type(NEW), type_=role_type(OLD),
                              existing_nullable=False)
