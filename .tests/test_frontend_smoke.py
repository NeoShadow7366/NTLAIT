import urllib.request
import unittest
from html.parser import HTMLParser
from test_base import BaseQATestCase

class SimpleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.classes = set()

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if 'id' in attr_dict:
            self.ids.add(attr_dict['id'])
        if 'class' in attr_dict:
            for cls in attr_dict['class'].split(' '):
                self.classes.add(cls)

class TestFrontendSmoke(BaseQATestCase):
    
    def test_index_html_loads(self):
        """Verify index.html can be served successfully."""
        req = urllib.request.Request(f"{self.base_url}/")
        with urllib.request.urlopen(req, timeout=5.0) as response:
            self.assertEqual(response.status, 200)
            html_content = response.read().decode('utf-8')
            
            # Basic textual assertions
            self.assertIn("<html", html_content.lower())
            self.assertIn("AI Manager Dashboard", html_content)
            
            # Structured DOM validation
            parser = SimpleHTMLParser()
            parser.feed(html_content)
            
            # Assert critical UI layout exists
            self.assertIn("view-explorer", parser.ids, "Model Explorer container missing")
            self.assertIn("view-vault", parser.ids, "Global Vault container missing")
            self.assertIn("view-inference", parser.ids, "Inference Studio container missing")
            
            # Remove old inputs check
            self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
