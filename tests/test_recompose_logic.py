import unittest
import pathlib
from recompose_logic import recompose_logic

class TestRecomposeLogic(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        self.expressions = recompose_logic(root / "data/PAUSCHALEN_Bedingungen.json")

    def test_c00_10a_logic(self):
        expected = "(((1)) OR 2 AND (3 AND 4 AND 5) AND 6 AND (7 AND 8 AND 9) AND 10 AND 11 AND 12 OR (13 AND 14))"
        self.assertEqual(self.expressions.get("C00.10A"), expected)

    def test_c00_10b_logic(self):
        expected = "(((1)) OR 2 AND (3 AND 4 AND 5) AND 6 AND (7 AND 8 AND 9) AND 10 AND 11 AND 12)"
        self.assertEqual(self.expressions.get("C00.10B"), expected)

if __name__ == "__main__":
    unittest.main()
