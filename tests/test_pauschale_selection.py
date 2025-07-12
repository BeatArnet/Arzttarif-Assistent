import unittest
import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from regelpruefer_pauschale import determine_applicable_pauschale


class TestPauschaleSelection(unittest.TestCase):
    def test_no_candidates(self):
        result = determine_applicable_pauschale(
            "", [], {}, [], [], {}, {}, {}, set()
        )
        self.assertEqual(result["type"], "Error")
        self.assertIn("potenziellen Pauschalen", result["message"])

    def test_candidates_none_valid(self):
        pauschalen_dict = {
            "X": {"Pauschale": "X", "Pauschale_Text": "x", "Taxpunkte": "1"}
        }
        bedingungen = [
            {"Pauschale": "X", "Bedingungstyp": "LKN", "Werte": "A"}
        ]
        result = determine_applicable_pauschale(
            "", [], {}, [], bedingungen, pauschalen_dict, {}, {}, {"X"}
        )
        self.assertEqual(result["type"], "Error")
        self.assertEqual(len(result.get("evaluated_pauschalen", [])), 1)
        first = result["evaluated_pauschalen"][0]
        self.assertIn("bedingungs_pruef_html", first)

    def test_specific_preferred_over_fallback(self):
        pauschalen_dict = {
            "X00.01A": {
                "Pauschale": "X00.01A",
                "Pauschale_Text": "Spec",
                "Taxpunkte": "50",
            },
            "C90.01A": {
                "Pauschale": "C90.01A",
                "Pauschale_Text": "Fallback",
                "Taxpunkte": "100",
            },
        }
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["A"]},
            [],
            [],
            pauschalen_dict,
            {},
            {},
            {"X00.01A", "C90.01A"},
        )
        self.assertEqual(result["details"]["Pauschale"], "X00.01A")
        self.assertTrue(result["bedingungs_pruef_html"].startswith("<"))

    def test_only_fallback_codes(self):
        pauschalen_dict = {
            "C90.01A": {
                "Pauschale": "C90.01A",
                "Pauschale_Text": "F1",
                "Taxpunkte": "100",
            },
            "C90.01B": {
                "Pauschale": "C90.01B",
                "Pauschale_Text": "F2",
                "Taxpunkte": "200",
            },
        }
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["A"]},
            [],
            [],
            pauschalen_dict,
            {},
            {},
            {"C90.01A", "C90.01B"},
        )
        self.assertEqual(result["details"]["Pauschale"], "C90.01B")
        self.assertTrue(result["bedingungs_pruef_html"].startswith("<"))


if __name__ == "__main__":
    unittest.main()
