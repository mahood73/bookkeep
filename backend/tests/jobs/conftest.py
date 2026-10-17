from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest
from app import database
from app.database import Base
from app.routers import jobs

@pytest.fixture
def sessions(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    monkeypatch.setattr(database,'SessionLocal',factory)
    monkeypatch.setattr(jobs,'_running_jobs',{})
    yield factory
    engine.dispose()


