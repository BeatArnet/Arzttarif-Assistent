import unittest
from flask import Flask
from flask_compress import Compress
import sys
import os

# Add parent directory to path to import server
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import create_app

class TestCompression(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_compression_enabled(self):
        # Request a large file (e.g., translations.json or just a large dummy response)
        # We'll simulate a large response
        @self.app.route('/large-response')
        def large_response():
            return "A" * 5000  # Should be enough to trigger compression (default min size is usually 500 bytes)

        response = self.client.get('/large-response', headers={'Accept-Encoding': 'gzip'})
        
        # Check if Content-Encoding header is set to gzip
        self.assertEqual(response.headers.get('Content-Encoding'), 'gzip')
        
        # Check if the content is actually compressed (length should be less than original)
        self.assertLess(len(response.data), 5000)

if __name__ == '__main__':
    unittest.main()
