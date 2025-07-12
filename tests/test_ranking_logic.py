import unittest
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import server

class TestRankingLogic(unittest.TestCase):
    def test_rare_tokens_get_priority(self):
        server.leistungskatalog_dict = {
            "A": {"Beschreibung": "commonterm"},
            "B": {"Beschreibung": "commonterm"},
            "C": {"Beschreibung": "commonterm rareterm"},
        }
        server.compute_token_doc_freq()
        ranked = server.rank_leistungskatalog_entries({"commonterm", "rareterm"}, limit=3)
        self.assertEqual(ranked[0], "C")

if __name__ == "__main__":
    unittest.main()
