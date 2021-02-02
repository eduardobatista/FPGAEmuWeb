"""Top Level Entity and Test Entity added to Database

Revision ID: b7e7b56ec514
Revises: a58afc2a6fd8
Create Date: 2021-01-27 02:15:37.948156

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e7b56ec514'
down_revision = 'a58afc2a6fd8'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user', sa.Column('testEntity', sa.String(length=256), nullable=True))
    op.add_column('user', sa.Column('topLevelEntity', sa.String(length=256), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user', 'topLevelEntity')
    op.drop_column('user', 'testEntity')
    # ### end Alembic commands ###