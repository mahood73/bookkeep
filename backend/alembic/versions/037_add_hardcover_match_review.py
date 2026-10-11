"""Persist reviewed Hardcover matches and unresolved library candidates."""
from alembic import op
import sqlalchemy as sa
revision = '037'
down_revision = '036'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('hardcover_matches',
        sa.Column('book_id', sa.Integer(), sa.ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('reviewed_hardcover_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pending_hardcover_id', sa.Integer(), nullable=True),
        sa.Column('pending_reason', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_table('hardcover_matches')
