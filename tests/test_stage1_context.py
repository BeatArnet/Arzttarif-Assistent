from server import _build_context_for_llm, _determine_final_billing, leistungskatalog_dict


def test_stage1_codes_prefer_specific_pauschale_when_available():
    rule_checked = [
        {
            "lkn": "C08.EC.0130",
            "typ": leistungskatalog_dict["C08.EC.0130"]["Typ"],
            "beschreibung": leistungskatalog_dict["C08.EC.0130"]["Beschreibung"],
            "menge": 1,
        },
        {
            "lkn": "WA.10.0010",
            "typ": leistungskatalog_dict["WA.10.0010"]["Typ"],
            "beschreibung": leistungskatalog_dict["WA.10.0010"]["Beschreibung"],
            "menge": 10,
        },
    ]
    regel_details = [
        {
            "lkn": "C08.EC.0130",
            "initiale_menge": 1,
            "finale_menge": 1,
            "regelpruefung": {"abrechnungsfaehig": True, "fehler": []},
        },
        {
            "lkn": "WA.10.0010",
            "initiale_menge": 10,
            "finale_menge": 10,
            "regelpruefung": {"abrechnungsfaehig": True, "fehler": []},
        },
    ]
    context = {
        "icd_input": [],
        "medication_inputs": [],
        "medication_atcs": [],
        "alter_context_val": None,
        "geschlecht_context_val": None,
        "use_icd_flag": False,
        "seitigkeit_context_val": "rechts",
        "anzahl_fuer_pauschale_context": None,
        "llm_validated_lkns": ["C08.EC.0130", "WA.10.0010", "C08.SA.1410"],
    }
    token_usage = {
        "llm_stage1": {"input_tokens": 0, "output_tokens": 0},
        "llm_stage2": {"input_tokens": 0, "output_tokens": 0},
    }

    result, _ = _determine_final_billing(
        rule_checked,
        regel_details,
        "Kiefergelenk, Luxation. Geschlossene Reposition mit Anästhesie",
        "de",
        context,
        token_usage,
    )

    assert result["details"]["Pauschale"] == "C08.50E"


def test_child_surcharge_code_is_present_in_stage1_context():
    context, _, _ = _build_context_for_llm(
        "Hausarztliche Konsultation 15 Min plus 10 Minuten Beratung; Kind 8 jaehrig",
        "de",
    )

    assert "CG.15.0010" in context


def test_bronchoscopy_stage1_context_includes_primary_procedure():
    context, _, _ = _build_context_for_llm("Bronchoskopie mit Lavage", "de")

    assert "C03.GC.0200" in context


def test_stage1_prompt_synonyms_do_not_list_catalog_titles():
    _, _, prompt_variants = _build_context_for_llm(
        "Korrekturop eines Hallux valgus rechts",
        "de",
    )

    assert prompt_variants
    assert prompt_variants[0].startswith("Korrekturop eines Hallux valgus")
    for variant in prompt_variants[1:]:
        assert "Operation bei Hallux valgus" not in variant
