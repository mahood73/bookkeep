from sqlalchemy import create_engine,text
from app.migration_bootstrap import legacy_revision


def test_tracked_old_revision_is_never_stamped_to_new_head():
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'))
        connection.execute(text("INSERT INTO alembic_version VALUES ('036')"))
    assert legacy_revision(engine) is None


def test_untracked_previous_schema_stamps_previous_revision_not_head():
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, oidc_subject VARCHAR)'))
        connection.execute(text('CREATE TABLE user_hardcover_sync (id INTEGER PRIMARY KEY)'))
    assert legacy_revision(engine)=='036'
