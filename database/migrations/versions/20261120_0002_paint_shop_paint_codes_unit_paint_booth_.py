"""paint shop: paint codes, unit paint, booth equipment; add missing current-run FK

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20

Also adds ``fk_image_current_run``: 0001 declared it with ``use_alter=True``
inside ``create_table``, which Alembic does not emit, so the constraint was never
created and ``inspection_images.current_run_id`` was not enforced.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paint_codes",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("metallic", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.add_column("production_units", sa.Column("paint_code", sa.String(length=20), nullable=True))
    op.create_foreign_key("fk_units_paint_code", "production_units", "paint_codes", ["paint_code"], ["code"])
    op.drop_constraint("ck_equipment_kind", "equipment", type_="check")
    op.create_check_constraint("ck_equipment_kind", "equipment", "kind in ('fixture','tool','camera','booth')")
    op.create_foreign_key("fk_image_current_run", "inspection_images", "inspection_runs", ["current_run_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_image_current_run", "inspection_images", type_="foreignkey")
    op.drop_constraint("ck_equipment_kind", "equipment", type_="check")
    # Paint booths recorded under 0002 cannot be expressed in the 0001 schema. Deleting them
    # would orphan their production events, so the old constraint is restored NOT VALID:
    # it applies to new rows, and existing booth rows stay readable.
    op.execute("ALTER TABLE equipment ADD CONSTRAINT ck_equipment_kind CHECK (kind in ('fixture','tool','camera')) NOT VALID")
    op.drop_constraint("fk_units_paint_code", "production_units", type_="foreignkey")
    op.drop_column("production_units", "paint_code")
    op.drop_table("paint_codes")
