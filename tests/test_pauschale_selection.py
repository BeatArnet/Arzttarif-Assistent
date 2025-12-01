import sys
import pathlib
import unittest
from collections import defaultdict

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from regelpruefer_pauschale import determine_applicable_pauschale


def build_indexes(pauschale_lp_data, bedingungen, tabellen_dict_by_table=None):
    """Create the index structures expected by determine_applicable_pauschale from test data."""
    pauschale_lp_index = defaultdict(set)
    for entry in pauschale_lp_data or []:
        pc = entry.get("Pauschale")
        lkn = entry.get("Leistungsposition")
        if pc and lkn:
            pauschale_lp_index[str(pc)].add(str(lkn).upper())

    pauschale_cond_lkn_index = defaultdict(set)
    pauschale_cond_table_index = defaultdict(set)
    for cond in bedingungen or []:
        pc = cond.get("Pauschale")
        typ = str(cond.get("Bedingungstyp", "")).upper()
        werte = cond.get("Werte")
        if not (pc and werte):
            continue
        if typ in {"LKN", "LEISTUNGSPOSITIONEN IN LISTE", "LKN IN LISTE"}:
            for value in str(werte).split(","):
                value_norm = value.strip().upper()
                if value_norm:
                    pauschale_cond_lkn_index[str(pc)].add(value_norm)
        elif typ in {"LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE", "LKN IN TABELLE"}:
            for table in str(werte).split(","):
                table_norm = table.strip().lower()
                if table_norm:
                    pauschale_cond_table_index[str(pc)].add(table_norm)

    lkn_to_tables_index = defaultdict(list)
    if tabellen_dict_by_table:
        for table_name, rows in tabellen_dict_by_table.items():
            table_norm = str(table_name).lower()
            for row in rows:
                if str(row.get("Tabelle_Typ", "")).lower() != "service_catalog":
                    continue
                code_val = row.get("Code")
                if code_val:
                    code_norm = str(code_val).upper()
                    if table_norm not in lkn_to_tables_index[code_norm]:
                        lkn_to_tables_index[code_norm].append(table_norm)

    return pauschale_lp_index, pauschale_cond_lkn_index, pauschale_cond_table_index, lkn_to_tables_index


class TestPauschaleSelection(unittest.TestCase):
    def test_no_candidates(self):
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], [])
        result = determine_applicable_pauschale(
            "",
            [],
            {},
            [],
            [],
            {},
            {},
            {},
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
            set(),
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
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], bedingungen)
        result = determine_applicable_pauschale(
            "",
            [],
            {},
            [],
            bedingungen,
            pauschalen_dict,
            {},
            {},
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
            {"X"},
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
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], [])
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["A"]},
            [],
            [],
            pauschalen_dict,
            {},
            {},
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
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
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], bedingungen)
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["X", "Y"], "useIcd": False},
            [],
            bedingungen,
            pauschalen_dict,
            {},
            {},
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
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
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], bedingungen)
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["X"], "useIcd": False},
            [],
            bedingungen,
            pauschalen_dict,
            {},
            {},
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
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
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], [])
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["A"]},
            [],
            [],
            pauschalen_dict,
            {},
            {},
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
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
        bedingungen = [
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
        ]
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], bedingungen)
        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["X"]},
            [],
            bedingungen,
            pauschalen_dict,
            {},
            {},
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
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
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes([], bedingungen, tabellen_dict_by_table)

        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["MATCH", "IRRLKN"], "useIcd": True},
            [],
            bedingungen,
            pauschalen_dict,
            leistungskatalog_dict,
            tabellen_dict_by_table,
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
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
        lp_index, cond_lkn_index, cond_table_index, lkn_table_index = build_indexes(pauschale_lp_data, bedingungen, tabellen_dict_by_table)

        result = determine_applicable_pauschale(
            "",
            [],
            {"LKN": ["MATCH", "WA.10.0050"], "useIcd": True},
            pauschale_lp_data,
            bedingungen,
            pauschalen_dict,
            leistungskatalog_dict,
            tabellen_dict_by_table,
            lp_index,
            cond_lkn_index,
            cond_table_index,
            lkn_table_index,
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
