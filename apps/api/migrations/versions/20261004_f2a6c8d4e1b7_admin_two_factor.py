"""admin two factor.

The Admin's TOTP second factor (ADR-0005), on the admin row itself — there is
one Admin, so there is one secret. All three columns are NULL until two-factor
is set up, and NULL again once it is disabled.

`totp_secret` is the active secret and `totp_pending_secret` one that
enrollment has issued but no code has yet proven; both hold only ciphertext,
sealed the way venue credentials are (ADR-0003). `totp_last_step` is the time
step of the last code accepted, so a code that was used once — and may have
been watched — is never accepted again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a6c8d4e1b7"
down_revision: str | None = "e8c4a1f6b2d9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("admin_user", sa.Column("totp_secret", sa.LargeBinary, nullable=True))
    op.add_column("admin_user", sa.Column("totp_pending_secret", sa.LargeBinary, nullable=True))
    op.add_column("admin_user", sa.Column("totp_last_step", sa.BigInteger, nullable=True))


def downgrade() -> None:
    op.drop_column("admin_user", "totp_last_step")
    op.drop_column("admin_user", "totp_pending_secret")
    op.drop_column("admin_user", "totp_secret")
