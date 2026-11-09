# tests/conftest.py
"""
Shared pytest fixtures for Cadenza.

Uses an in-memory SQLite database so tests run without any external services.
"""
import os
import pytest

# Point to SQLite only if DATABASE_URL is not set in the environment
test_db_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", test_db_url)
os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.fixture(scope="session")
def app():
    from api.app import app as flask_app
    flask_app.config.update(
        TESTING=True,
    )
    from api.models import db
    with flask_app.app_context():
        db.create_all()
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()
