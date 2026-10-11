"""Recognize legacy untracked schemas without skipping new migrations."""
import os
from sqlalchemy import create_engine, inspect, text

def legacy_revision(engine):
    schema = inspect(engine)
    if schema.has_table('alembic_version'):
        with engine.connect() as connection:
            if connection.execute(text('SELECT version_num FROM alembic_version')).first():
                return None
    if not schema.has_table('users'):
        return None
    columns = {column['name'] for column in schema.get_columns('users')}
    if 'oidc_subject' not in columns:
        return '034'
    if not schema.has_table('user_hardcover_sync'):
        return '035'
    if not schema.has_table('hardcover_matches'):
        return '036'
    return '037'

if __name__ == '__main__':
    engine = create_engine(os.environ['DATABASE_URL'])
    try:
        print(legacy_revision(engine) or '')
    finally:
        engine.dispose()
