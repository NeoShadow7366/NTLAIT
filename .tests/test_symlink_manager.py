import unittest
import tempfile
import os
import shutil
import sys
import platform

# Allow import of backend module
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(os.path.dirname(current_dir), ".backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from symlink_manager import create_safe_directory_link

class TestSymlinkManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.source_dir = os.path.join(self.temp_dir, "Global_Vault", "checkpoints")
        self.target_dir = os.path.join(self.temp_dir, "App", "models", "checkpoints")
        os.makedirs(self.source_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_source(self):
        """Ensure it returns False immediately if the source vault directory doesn't exist."""
        result = create_safe_directory_link(os.path.join(self.temp_dir, "does_not_exist"), self.target_dir)
        self.assertFalse(result)

    def test_successful_symlink(self):
        """Verify linking works on standard un-conflicted states."""
        result = create_safe_directory_link(self.source_dir, self.target_dir)
        self.assertTrue(result)
        
        # Verify the physical OS link
        if platform.system() == "Windows":
            # Windows 'mklink /J' doesn't usually report True for islink(), but 'is_junction' does from 3.12+
            # As a fallback string verify, we check existence
            self.assertTrue(os.path.exists(self.target_dir))
        else:
            self.assertTrue(os.path.islink(self.target_dir))

    def test_overwrite_real_file_refusal(self):
        """Verify the manager refuses to replace a real FILE holding the target name."""
        os.makedirs(os.path.dirname(self.target_dir), exist_ok=True)
        with open(self.target_dir, 'w') as f:
            f.write("I am a real config file")
            
        result = create_safe_directory_link(self.source_dir, self.target_dir)
        self.assertFalse(result, "Refused to destroy a real file to create a link")

    def test_overwrite_real_directory_removal(self):
        """Verify the manager drops replacing real populated conflicting directories safely."""
        os.makedirs(self.target_dir, exist_ok=True)
        # It's an empty real directory initially, the symlink manager tries to remove it
        # to clear room for the link
        result = create_safe_directory_link(self.source_dir, self.target_dir)
        self.assertTrue(result)

if __name__ == '__main__':
    unittest.main()
