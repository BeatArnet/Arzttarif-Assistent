import unittest
import sys
import pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import server

class TestAnesthesiaMapping(unittest.TestCase):
    def test_wa10_codes_added_when_anesthesia_present(self):
        potential = {"P1"}
        conditions = [
            {"Pauschale": "P1", "Bedingungstyp": "LEISTUNGSPOSITIONEN IN LISTE", "Werte": "WA.20.0010"}
        ]
        tabellen = {
            "anast": [
                {"Code": "WA.10.0010", "Code_Text": "MAC", "Tabelle_Typ": "service_catalog"},
                {"Code": "WA.10.0020", "Code_Text": "Klasse I", "Tabelle_Typ": "service_catalog"}
            ]
        }
        leistungskatalog = {
            "WA.20.0010": {"Beschreibung": "Sedierung"},
            "WA.10.0010": {"Beschreibung": "MAC"},
            "WA.10.0020": {"Beschreibung": "Klasse I"},
        }

        result = server.get_LKNs_from_pauschalen_conditions(potential, conditions, tabellen, leistungskatalog)
        self.assertIn("WA.20.0010", result)
        self.assertIn("WA.10.0010", result)
        self.assertIn("WA.10.0020", result)

if __name__ == "__main__":
    unittest.main()
