import unittest
import sys
import os

if __name__ == '__main__':
    # Ensure current directory is accessible
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    print("Running QA Guardian Full Suite...")
    loader = unittest.TestLoader()
    suite = loader.discover('g:/AG SM/.tests', pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if not result.wasSuccessful():
        sys.exit(1)
    sys.exit(0)
