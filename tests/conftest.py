# tests/conftest.py
"""
Shared pytest fixtures for Cadenza.

Uses an in-memory SQLite database so tests run without any external services.
"""
import os
import pytest

# Point to SQLite before the app module is imported so db.create_all() builds
# the right engine.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
# Suppress Redis (graceful fallback will kick in)
os.environ.pop("REDIS_URL", None)


@pytest.fixture(scope="session")
def app():
    from api.app import app as flask_app
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    from api.models import db
    with flask_app.app_context():
        db.create_all()
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()
