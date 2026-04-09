"""Shared pytest fixtures."""
import pytest
from unittest.mock import MagicMock
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture(autouse=True)
def _block_db(monkeypatch):
    """Prevent any test from accidentally connecting to the real database."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://blocked:blocked@localhost/blocked-test-sentinel")


@pytest.fixture(autouse=True)
def _block_garmin(monkeypatch):
    """Prevent any test from accidentally calling the real Garmin API."""
    def _fail():
        raise RuntimeError("Use the garmin_client fixture — real Garmin client not allowed in tests")
    monkeypatch.setattr("cli.get_client", _fail)


@pytest.fixture
def db():
    """In-memory SQLite session with all tables created. Fresh per test."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def garmin_client(db, monkeypatch):
    """Mock Garmin client with empty detail/polyline responses. Depends on db."""
    client = MagicMock()
    client.get_activity.return_value = {}
    client.get_activity_details.return_value = {}
    monkeypatch.setattr("cli.get_client", lambda: client)
    monkeypatch.setattr("cli.match_activity_to_routes", lambda *_: None)
    return client
