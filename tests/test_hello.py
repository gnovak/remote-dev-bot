#!/usr/bin/env python3

import unittest
import sys
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from hello import main

class TestHello(unittest.TestCase):
    def test_hello_output(self):
        """Test that main() prints the expected message"""
        captured_output = io.StringIO()
        sys.stdout = captured_output

        main()

        sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        self.assertEqual(output.strip(), 'Hello from Remote Dev Bot')

if __name__ == '__main__':
    unittest.main()
