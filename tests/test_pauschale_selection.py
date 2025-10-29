import sys
import pathlib
import unittest

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

    def test_prefers_higher_lkn_match_count(self):
        pauschalen_dict = {
            "A": {"Pauschale": "A", "Pauschale_Text": "Jaw", "Taxpunkte": "120"},
            "B": {"Pauschale": "B", "Pauschale_Text": "Sedation", "Taxpunkte": "300"},
        }
        bedingungen = [
            {"Pauschale": "A", "BedingungsID": 1, "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE", "Gruppe": 1, "Operator": "UND", "Werte": "Y"},
            {"Pauschale": "A", "BedingungsID": 2, "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE", "Gruppe": 1, "Operator": "UND", "Werte": "X"},
            {"Pauschale": "B", "BedingungsID": 3, "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE", "Gruppe": 1, "Operator": "UND", "Werte": "X"},
        ]
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["X", "Y"], "useIcd": False},
            [],
            bedingungen,
            pauschalen_dict,
            {},
            {},
            {"A", "B"},
        )
        self.assertEqual(result["details"]["Pauschale"], "A")


    def test_use_icd_false_prefers_non_icd_candidates(self):
        pauschalen_dict = {
            "A": {"Pauschale": "A", "Pauschale_Text": "ICD-Pauschale", "Taxpunkte": "200"},
            "B": {"Pauschale": "B", "Pauschale_Text": "Ohne ICD", "Taxpunkte": "150"},
        }
        bedingungen = [
            {
                "Pauschale": "A",
                "Bedingungstyp": "ICD",
                "Werte": "S03.0",
            },
            {
                "Pauschale": "B",
                "Bedingungstyp": "LKN",
                "Werte": "X",
            },
        ]
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["X"], "useIcd": False},
            [],
            bedingungen,
            pauschalen_dict,
            {},
            {},
            {"A", "B"},
        )
        self.assertEqual(result["details"]["Pauschale"], "B")


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
        self.assertEqual(result["details"]["Pauschale"], "C90.01A")
        self.assertTrue(result["bedingungs_pruef_html"].startswith("<"))

    def test_prefers_higher_letter_priority(self):
        pauschalen_dict = {
            "C06.00A": {
                "Pauschale": "C06.00A",
                "Pauschale_Text": "A-Variante",
                "Taxpunkte": "150",
            },
            "C06.00B": {
                "Pauschale": "C06.00B",
                "Pauschale_Text": "B-Variante",
                "Taxpunkte": "180",
            },
        }
        # Beide Kandidaten erfüllen dieselben Bedingungen mit gleicher Match-Anzahl.
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["X"]},
            [],
            [
                {
                    "Pauschale": "C06.00A",
                    "Bedingungstyp": "LKN",
                    "Werte": "X",
                },
                {
                    "Pauschale": "C06.00B",
                    "Bedingungstyp": "LKN",
                    "Werte": "X",
                },
            ],
            pauschalen_dict,
            {},
            {},
            {"C06.00A", "C06.00B"},
        )

        self.assertEqual(result["details"]["Pauschale"], "C06.00A")

    def test_filters_candidates_with_only_irrelevant_table_hits(self):
        pauschalen_dict = {
            "A01.00A": {
                "Pauschale": "A01.00A",
                "Pauschale_Text": "Valide Option",
                "Taxpunkte": "200",
            },
            "B01.00A": {
                "Pauschale": "B01.00A",
                "Pauschale_Text": "Nur OR Tabelle",
                "Taxpunkte": "50",
            },
        }
        bedingungen = [
            {
                "Pauschale": "A01.00A",
                "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE",
                "Werte": "MATCH",
                "Gruppe": 1,
                "Operator": "UND",
            },
            {
                "Pauschale": "B01.00A",
                "Bedingungstyp": "LKN IN TABELLE",
                "Werte": "OR",
                "Gruppe": 1,
                "Operator": "UND",
            },
            {
                "Pauschale": "B01.00A",
                "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE",
                "Werte": "ANDERE",
                "Gruppe": 1,
                "Operator": "UND",
            },
        ]
        tabellen_dict_by_table = {
            "or": [
                {
                    "Code": "IRRLKN",
                    "Tabelle_Typ": "service_catalog",
                }
            ],
            "weitere": [
                {
                    "Code": "IRRLKN",
                    "Tabelle_Typ": "service_catalog",
                }
            ],
        }
        leistungskatalog_dict = {
            "MATCH": {"Beschreibung": "Match"},
            "IRRLKN": {"Beschreibung": "Irr"},
        }

        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["MATCH", "IRRLKN"], "useIcd": True},
            [],
            bedingungen,
            pauschalen_dict,
            leistungskatalog_dict,
            tabellen_dict_by_table,
        )

        evaluated_codes = {cand["code"] for cand in result.get("evaluated_pauschalen", [])}
        self.assertIn("B01.00A", evaluated_codes)

        irrelevant_candidate = next(
            cand for cand in result["evaluated_pauschalen"] if cand["code"] == "B01.00A"
        )
        self.assertEqual(
            irrelevant_candidate["lkn_match_sources"],
            [{"lkn": "IRRLKN", "source": "table", "table": "or"}],
        )

        erklaerung = result["details"].get("pauschale_erklaerung_html", "")
        self.assertIn("A01.00A", erklaerung)
        self.assertNotIn("B01.00A", erklaerung)

    def test_filters_candidates_with_only_anast_matches(self):
        pauschalen_dict = {
            "A01.00A": {
                "Pauschale": "A01.00A",
                "Pauschale_Text": "Valide Option",
                "Taxpunkte": "200",
            },
            "B01.00A": {
                "Pauschale": "B01.00A",
                "Pauschale_Text": "Nur Anästhesie",
                "Taxpunkte": "50",
            },
        }
        bedingungen = [
            {
                "Pauschale": "A01.00A",
                "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE",
                "Werte": "MATCH",
                "Gruppe": 1,
                "Operator": "UND",
            },
            {
                "Pauschale": "B01.00A",
                "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE",
                "Werte": "WA.10.0050",
                "Gruppe": 1,
                "Operator": "UND",
            },
            {
                "Pauschale": "B01.00A",
                "Bedingungstyp": "LEISTUNGSPOSITIONEN IN TABELLE",
                "Werte": "ANAST",
                "Gruppe": 1,
                "Operator": "UND",
            },
            {
                "Pauschale": "B01.00A",
                "Bedingungstyp": "ICD",
                "Werte": "NO_MATCH",
                "Gruppe": 1,
                "Operator": "UND",
            },
        ]
        pauschale_lp_data = [
            {"Pauschale": "A01.00A", "Leistungsposition": "MATCH"},
            {"Pauschale": "B01.00A", "Leistungsposition": "WA.10.0050"},
        ]
        tabellen_dict_by_table = {
            "anast": [
                {
                    "Code": "WA.10.0050",
                    "Tabelle_Typ": "service_catalog",
                }
            ]
        }
        leistungskatalog_dict = {
            "MATCH": {"Beschreibung": "Match"},
            "WA.10.0050": {"Beschreibung": "Anästhesie"},
        }

        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["MATCH", "WA.10.0050"], "useIcd": True},
            pauschale_lp_data,
            bedingungen,
            pauschalen_dict,
            leistungskatalog_dict,
            tabellen_dict_by_table,
        )

        evaluated_codes = {cand["code"] for cand in result.get("evaluated_pauschalen", [])}
        self.assertIn("B01.00A", evaluated_codes)

        anast_candidate = next(
            cand for cand in result["evaluated_pauschalen"] if cand["code"] == "B01.00A"
        )
        self.assertEqual(
            anast_candidate["lkn_match_sources"],
            [
                {"lkn": "WA.10.0050", "source": "direct", "table": None},
                {"lkn": "WA.10.0050", "source": "table", "table": "anast"},
            ],
        )

        erklaerung = result["details"].get("pauschale_erklaerung_html", "")
        self.assertIn("A01.00A", erklaerung)
        self.assertNotIn("B01.00A", erklaerung)


if __name__ == "__main__":
    unittest.main()
