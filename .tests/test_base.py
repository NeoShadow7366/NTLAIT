import unittest
import threading
import tempfile
import os
import sys
import shutil
import sqlite3
from http.server import ThreadingHTTPServer

# Add .backend to sys.path so we can import server.py and metadata_db
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_path = os.path.join(PROJECT_ROOT, ".backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import server
from metadata_db import MetadataDB

class IsolatedServerThread(threading.Thread):
    def __init__(self, temp_dir):
        super().__init__(daemon=True)
        self.temp_dir = temp_dir
        self.server = None
        self.port = None

    def run(self):
        # Override server paths to use temp folder for data isolation
        server.AIWebServer.root_dir = self.temp_dir
        server.AIWebServer.db_path = os.path.join(self.temp_dir, ".backend", "metadata.sqlite")
        
        # Keep static_dir pointing to the real static folder so test_frontend_smoke can fetch index.html
        server.AIWebServer.static_dir = os.path.join(PROJECT_ROOT, ".backend", "static")
        
        self.server = ThreadingHTTPServer(('localhost', 0), server.AIWebServer)
        self.port = self.server.server_port
        self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


class BaseQATestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up an isolated temporary workspace and a background HTTP server."""
        cls.temp_dir = tempfile.mkdtemp()
        
        # Create mock directory structure
        os.makedirs(os.path.join(cls.temp_dir, ".backend", "recipes"))
        os.makedirs(os.path.join(cls.temp_dir, "Global_Vault", "checkpoints"))
        os.makedirs(os.path.join(cls.temp_dir, "packages"))
        
        # Initialize an empty metadata SQLite DB in the temp dir
        cls.db_path = os.path.join(cls.temp_dir, ".backend", "metadata.sqlite")
        db = MetadataDB(cls.db_path) # Automatically creates tables
        
        # Start server in background
        cls.server_thread = IsolatedServerThread(cls.temp_dir)
        cls.server_thread.start()
        
        # Wait for port assignment
        while cls.server_thread.port is None:
            pass
        
        cls.base_url = f"http://localhost:{cls.server_thread.port}"

    @classmethod
    def tearDownClass(cls):
        """Shut down the background server and delete the temporary workspace."""
        if cls.server_thread:
            cls.server_thread.stop()
            cls.server_thread.join()
        if os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir, ignore_errors=True)
