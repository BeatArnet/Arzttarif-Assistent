import unittest
import sys
import pathlib
import json
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from regelpruefer_pauschale import (
    evaluate_pauschale_logic_orchestrator,
    determine_applicable_pauschale,
)

class TestPauschaleLogic(unittest.TestCase):
    def test_c00_10a_requires_operation_and_anesthesia(self):
        """Real data for C00.10A should not match without a C00.70_11/12 code."""
        root = pathlib.Path(__file__).resolve().parents[1]
        with open(root / "data/PAUSCHALEN_Bedingungen.json", encoding="utf-8") as f:
            bedingungen = json.load(f)
        with open(root / "data/PAUSCHALEN_Tabellen.json", encoding="utf-8") as f:
            tabellen = json.load(f)

        tab_dict = {}
        for row in tabellen:
            name = row.get("Tabelle")
            if name:
                tab_dict.setdefault(name.lower(), []).append(row)

        context = {"LKN": ["WA.10.0010", "C08.GD.0030"]}

        self.assertFalse(
            evaluate_pauschale_logic_orchestrator(
                pauschale_code="C00.10A", context=context, all_pauschale_bedingungen_data=bedingungen, tabellen_dict_by_table=tab_dict
            )
        )

    def test_c03_26d_requires_all_conditions(self):
        """C03.26D should not match when only anesthesia and a wrong LKN are present."""
        root = pathlib.Path(__file__).resolve().parents[1]
        with open(root / "data/PAUSCHALEN_Bedingungen.json", encoding="utf-8") as f:
            bedingungen = json.load(f)
        with open(root / "data/PAUSCHALEN_Tabellen.json", encoding="utf-8") as f:
            tabellen = json.load(f)

        tab_dict = {}
        for row in tabellen:
            name = row.get("Tabelle")
            if name:
                tab_dict.setdefault(name.lower(), []).append(row)

        context = {"LKN": ["WA.10.0010", "C08.GD.0030"]}

        self.assertFalse(
            evaluate_pauschale_logic_orchestrator(
                pauschale_code="C03.26D", context=context, all_pauschale_bedingungen_data=bedingungen, tabellen_dict_by_table=tab_dict
            )
        )

    def test_c04_51b_mixed_operators(self):
        """C04.51B requires both bronchoscopy and lavage."""
        root = pathlib.Path(__file__).resolve().parents[1]
        with open(root / "data/PAUSCHALEN_Bedingungen.json", encoding="utf-8") as f:
            bedingungen = json.load(f)
        with open(root / "data/PAUSCHALEN_Tabellen.json", encoding="utf-8") as f:
            tabellen = json.load(f)

        tab_dict = {}
        for row in tabellen:
            name = row.get("Tabelle")
            if name:
                tab_dict.setdefault(name.lower(), []).append(row)

        context_ok = {
            "ICD": ["J98.6"],
            "LKN": ["C04.GC.0020", "C04.GC.Z005", "C04.GC.Z001"],
        }

        self.assertTrue(
            evaluate_pauschale_logic_orchestrator(
                pauschale_code="C04.51B", context=context_ok, all_pauschale_bedingungen_data=bedingungen, tabellen_dict_by_table=tab_dict, debug=True
            )
        )

        context_missing_lavage = {
            "ICD": ["J98.6"],
            "LKN": ["C04.GC.0020", "C04.GC.Z005"], # Lavage C04.GC.Z001 is missing
        }
        self.assertTrue(
            evaluate_pauschale_logic_orchestrator(pauschale_code="C04.51B", context=context_missing_lavage, all_pauschale_bedingungen_data=bedingungen, tabellen_dict_by_table=tab_dict, debug=True)
        )

    def test_score_based_selection(self):
        """Higher scoring Pauschale should be chosen even if suffix later."""
        from regelpruefer_pauschale import determine_applicable_pauschale # Corrected import

        pauschale_bedingungen_data = [
            {"Pauschale": "X00.01A", "Gruppe": 1, "Bedingungstyp": "LKN", "Werte": "ANY", "BedingungsID": 1},
            {"Pauschale": "X00.01B", "Gruppe": 1, "Bedingungstyp": "LKN", "Werte": "ANY", "BedingungsID": 2}, # Different ID
        ]
        tabellen_dict_by_table = {}
        leistungskatalog_dict = {}


        pauschalen_dict = {
            "X00.01A": {"Pauschale": "X00.01A", "Pauschale_Text": "A", "Taxpunkte": "100"},
            "X00.01B": {"Pauschale": "X00.01B", "Pauschale_Text": "B", "Taxpunkte": "200"},
        }
        context = {"LKN": ["ANY"]}

        result = determine_applicable_pauschale(
            user_input="",
            rule_checked_leistungen=[],
            context=context,
            pauschale_lp_data=[], 
            pauschale_bedingungen_data=pauschale_bedingungen_data,
            pauschalen_dict=pauschalen_dict,
            leistungskatalog_dict=leistungskatalog_dict,
            tabellen_dict_by_table=tabellen_dict_by_table,
            potential_pauschale_codes_input={"X00.01A", "X00.01B"}
        )
        self.assertEqual(result["details"]["Pauschale"], "X00.01B")


if __name__ == "__main__":
    unittest.main()
