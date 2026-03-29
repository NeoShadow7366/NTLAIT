import pytest
import tempfile
import os
import sys
import shutil
from test_base import IsolatedServerThread

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@pytest.fixture(scope="session")
def app_server():
    """
    Spins up the test Python server on a background thread.
    Exposes the URL for the frontend E2E playwright tests.
    """
    temp_dir = tempfile.mkdtemp()
    
    # Create required sub-directories to prevent crashing
    os.makedirs(os.path.join(temp_dir, ".backend", "recipes"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "Global_Vault", "checkpoints"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "packages"), exist_ok=True)
    
    from metadata_db import MetadataDB
    db_path = os.path.join(temp_dir, ".backend", "metadata.sqlite")
    # Generate tables
    db = MetadataDB(db_path)
    
    # Threaded application server bound to ephemeral port 0
    server_thread = IsolatedServerThread(temp_dir)
    server_thread.start()
    
    if not server_thread.startup_event.wait(timeout=3.0):
        raise RuntimeError("Test server failed to bind port within 3s")
        
    url = f"http://localhost:{server_thread.port}"
    
    yield url
    
    # Teardown
    server_thread.stop()
    server_thread.join(timeout=3.0)
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture(scope="session")
def base_url(app_server):
    """
    Overrides pytest-playwright's built-in `base_url` fixture
    so page.goto("/") automatically points to our local ephemeral server.
    """
    return app_server
