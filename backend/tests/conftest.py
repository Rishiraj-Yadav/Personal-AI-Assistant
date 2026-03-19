"""
Pytest Configuration for SonarBot Tests

Provides fixtures and configuration for all test modules.
"""

import pytest
import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set minimal environment variables for testing BEFORE any imports
os.environ.setdefault('GROQ_API_KEY', 'test_groq_key_12345')
os.environ.setdefault('GOOGLE_API_KEY', 'test_google_key_12345')
os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_data.db')
os.environ.setdefault('DEBUG', 'true')
os.environ.setdefault('DESKTOP_AGENT_URL', 'http://localhost:7777')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_env():
    """Fixture to temporarily modify environment variables"""
    original = os.environ.copy()
    yield os.environ
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture
async def async_db():
    """Fixture for async database testing"""
    from app.database.async_base import init_async_db, close_async_db

    await init_async_db()
    yield
    await close_async_db()


@pytest.fixture
def temp_dir(tmp_path):
    """Fixture for temporary directory"""
    return tmp_path


# Configure pytest-asyncio
pytest_plugins = ['pytest_asyncio']
