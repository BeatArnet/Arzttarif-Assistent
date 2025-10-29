from utils import extract_patient_demographics, PatientDemographics


def test_extracts_explicit_age_and_gender_from_text():
    info: PatientDemographics = extract_patient_demographics("Kind 8 jaehrig, maennlich")
    assert info.get("age_value") == 8
    assert info.get("age_operator") == "="
    assert info.get("age_source") == "text"
    assert info.get("gender") == "m"
    assert info.get("gender_source") == "text"


def test_extracts_comparator_from_language_variants():
    info: PatientDemographics = extract_patient_demographics("Patient unter 12 Jahren, weiblich")
    assert info.get("age_value") == 12
    assert info.get("age_operator") in {"<", "<="}
    assert info.get("age_source") == "text"
    assert info.get("gender") == "w"


def test_infers_child_when_only_keyword_present():
    info: PatientDemographics = extract_patient_demographics("Beratung fuer Kind mit akutem Husten")
    assert info.get("age_value") == 12
    assert info.get("age_operator") == "<="
    assert info.get("age_source") == "inferred"


def test_demographic_matching_returns_child_surcharge():
    from server import load_data, _match_codes_for_demographics

    load_data()
    demo: PatientDemographics = {"age_value": 8, "age_operator": "=", "gender": "m"}
    matches = _match_codes_for_demographics(demo)
    assert "CG.15.0010" in matches


def test_demographic_matching_ignores_non_surcharge_gender_codes():
    from server import load_data, _match_codes_for_demographics

    load_data()
    demo: PatientDemographics = {"gender": "w"}
    matches = _match_codes_for_demographics(demo)
    assert "GK.10.0010" not in matches


