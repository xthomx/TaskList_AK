import re
import unittest

import main


class HelpPageTests(unittest.TestCase):
    def test_help_page_is_inlined_with_all_sections_and_valid_links(self):
        html = main.build_html()
        self.assertIn('id="helpPage"', html)
        self.assertNotIn('<!--HELP-->', html)
        sections = re.findall(r'<section id="(h-[a-z]+)"', html)
        self.assertEqual(len(sections), 20)
        links = re.findall(r'<a href="#(h-[a-z]+)"', html)
        self.assertEqual(sorted(links), sorted(sections))          # każdy punkt spisu treści prowadzi do sekcji
        self.assertEqual(html.count('<figure'), html.count('</figure>'))
        self.assertEqual(html.count('<section'), html.count('</section>'))


if __name__ == '__main__':
    unittest.main()
