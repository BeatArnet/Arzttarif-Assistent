import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import regelpruefer_einzelleistungen as rp


@pytest.fixture(autouse=True)
def reset_kumulation(monkeypatch):
    monkeypatch.setattr(rp, "KUMULATION_EXPLIZIT", 0)


def test_nur_kumulierbar_kapitel_allows_prefix():
    regelwerk = {
        "AA.00.0001": [{"Typ": "Nur kumulierbar (X, V) mit", "LKNs": ["Kapitel CA.05"]}]
    }
    fall = {"LKN": "AA.00.0001", "Begleit_LKNs": ["CA.05.0010"]}
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk)
    assert result["abrechnungsfaehig"]
    assert result["fehler"] == []


def test_nur_kumulierbar_kapitel_rejects_other_prefix():
    regelwerk = {
        "AA.00.0001": [{"Typ": "Nur kumulierbar (X, V) mit", "LKNs": ["Kapitel CA.05"]}]
    }
    fall = {"LKN": "AA.00.0001", "Begleit_LKNs": ["CA.10.0010"]}
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk)
    assert not result["abrechnungsfaehig"]
    assert any("Nur kumulierbar" in msg for msg in result["fehler"])


def test_kumulierbar_leistungsgruppe_allows_member():
    regelwerk = {
        "AA.00.0002": [
            {
                "Typ": "Kumulierbar (I, V) mit",
                "LKNs": ["Leistungsgruppe LG-001"],
            }
        ]
    }
    lg_map = {"LG-001": ["CA.10.0010", "CA.10.0020"]}
    fall = {"LKN": "AA.00.0002", "Begleit_LKNs": ["CA.10.0010"]}
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk, lg_map)
    assert result["abrechnungsfaehig"]
    assert result["fehler"] == []


def test_kumulierbar_leistungsgruppe_allows_member_when_explicit(monkeypatch):
    monkeypatch.setattr(rp, "KUMULATION_EXPLIZIT", 1)
    regelwerk = {
        "AA.00.0002": [
            {
                "Typ": "Kumulierbar (I, V) mit",
                "LKNs": ["Leistungsgruppe LG-001"],
            }
        ]
    }
    lg_map = {"LG-001": ["CA.10.0010", "CA.10.0020"]}
    fall = {"LKN": "AA.00.0002", "Begleit_LKNs": ["CA.10.0010"]}
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk, lg_map)
    assert result["abrechnungsfaehig"]
    assert result["fehler"] == []


def test_kumulierbar_leistungsgruppe_allows_non_member():
    regelwerk = {
        "AA.00.0002": [
            {
                "Typ": "Kumulierbar (I, V) mit",
                "LKNs": ["Leistungsgruppe LG-001"],
            }
        ]
    }
    lg_map = {"LG-001": ["CA.10.0010", "CA.10.0020"]}
    fall = {"LKN": "AA.00.0002", "Begleit_LKNs": ["CA.11.0010"]}
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk, lg_map)
    assert result["abrechnungsfaehig"]
    assert result["fehler"] == []


def test_kumulierbar_leistungsgruppe_rejects_non_member_when_explicit(monkeypatch):
    monkeypatch.setattr(rp, "KUMULATION_EXPLIZIT", 1)
    regelwerk = {
        "AA.00.0002": [
            {
                "Typ": "Kumulierbar (I, V) mit",
                "LKNs": ["Leistungsgruppe LG-001"],
            }
        ]
    }
    lg_map = {"LG-001": ["CA.10.0010", "CA.10.0020"]}
    fall = {"LKN": "AA.00.0002", "Begleit_LKNs": ["CA.11.0010"]}
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk, lg_map)
    assert not result["abrechnungsfaehig"]
    assert any("Nur kumulierbar" in msg for msg in result["fehler"])


def test_moegliche_zusatzpositionen_does_not_restrict_when_explicit(monkeypatch):
    monkeypatch.setattr(rp, "KUMULATION_EXPLIZIT", 1)
    regelwerk = {
        "AA.00.0010": [{"Typ": "Mögliche Zusatzpositionen", "LKNs": ["AA.00.0020"]}]
    }
    fall = {
        "LKN": "AA.00.0010",
        "Begleit_LKNs": ["AA.00.0020", "MK.05.0070"],
    }
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk)
    assert result["abrechnungsfaehig"]
    assert result["fehler"] == []


def test_case_insensitive_lkn_and_begleit():
    regelwerk = {
        "C06.CE.0010": [{"Typ": "Nur als Zuschlag zu", "LKN": "C00.YY.0260"}]
    }
    fall = {"LKN": "c06.ce.0010", "Begleit_LKNs": ["c00.yy.0260"]}
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk)
    assert result["abrechnungsfaehig"]


def test_nicht_kumulierbar_mit_typ_filter_blockiert():
    regelwerk = {
        "AA.00.0010": [
            {"Typ": "Nicht kumulierbar (E, V) mit", "LKNs": ["CA.00.0010"]}
        ]
    }
    fall = {
        "LKN": "AA.00.0010",
        "Typ": "E",
        "Begleit_LKNs": ["CA.00.0010"],
        "Begleit_Typen": {"CA.00.0010": "E"}
    }
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk)
    assert not result["abrechnungsfaehig"]
    assert any("Nicht kumulierbar" in msg for msg in result["fehler"])


def test_nur_als_zuschlag_verlangt_basis():
    regelwerk = {"AA.00.0020": [{"Typ": "Nur als Zuschlag zu", "LKNs": ["AA.00.0010"]}]}
    fall = {
        "LKN": "AA.00.0020",
        "Menge": 3,
        "Begleit_LKNs": [],
        "Begleit_Typen": {}
    }
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk)
    assert not result["abrechnungsfaehig"]
    assert any("Nur als Zuschlag" in msg for msg in result["fehler"])


def test_nur_als_zuschlag_basis_vorhanden():
    regelwerk = {"AA.00.0020": [{"Typ": "Nur als Zuschlag zu", "LKNs": ["AA.00.0010"]}]}
    fall = {
        "LKN": "AA.00.0020",
        "Menge": 3,
        "Begleit_LKNs": ["AA.00.0010"],
        "Begleit_Typen": {"AA.00.0010": "E"}
    }
    result = rp.pruefe_abrechnungsfaehigkeit(fall, regelwerk)
    assert result["abrechnungsfaehig"]
