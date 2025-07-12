import unittest
import sys
import pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from utils import expand_compound_words


class TestExpandCompoundWords(unittest.TestCase):
    def test_known_prefix_expanded(self):
        text = "Linksherzkatheter"
        result = expand_compound_words(text)
        self.assertIn("links herzkatheter", result)
        self.assertIn("herzkatheter", result)

    def test_ordinary_words_unchanged(self):
        for word in ["Untersuchung", "unterwegs"]:
            self.assertEqual(expand_compound_words(word), word)


if __name__ == "__main__":
    unittest.main()
