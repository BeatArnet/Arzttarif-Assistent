from typing import Any, Dict, List, Set, Tuple
from utils import expand_compound_words, extract_keywords

def compute_token_doc_freq(
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    token_doc_freq: Dict[str, int],
) -> None:
    """Compute document frequency for tokens across the Leistungskatalog."""
    token_doc_freq.clear()
    for details in leistungskatalog_dict.values():
        texts = []
        for base in [
            "Beschreibung",
            "Beschreibung_f",
            "Beschreibung_i",
            "MedizinischeInterpretation",
            "MedizinischeInterpretation_f",
            "MedizinischeInterpretation_i",
        ]:
            val = details.get(base)
            if val:
                texts.append(str(val))
        combined = " ".join(texts)
        tokens = extract_keywords(combined)
        for t in tokens:
            token_doc_freq[t] = token_doc_freq.get(t, 0) + 1

def rank_leistungskatalog_entries(
    tokens: Set[str],
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    token_doc_freq: Dict[str, int],
    limit: int = 200,
    return_scores: bool = False,
) -> List[str] | List[Tuple[float, str]]:
    """Return LKN codes ranked by weighted token occurrences.

    If ``return_scores`` is ``True`` the result is a list of ``(score, code)``
    tuples, otherwise just the codes are returned.
    """
    scored: List[Tuple[float, str]] = []
    for lkn_code, details in leistungskatalog_dict.items():
        texts = []
        for base in [
            "Beschreibung",
            "Beschreibung_f",
            "Beschreibung_i",
            "MedizinischeInterpretation",
            "MedizinischeInterpretation_f",
            "MedizinischeInterpretation_i",
        ]:
            val = details.get(base)
            if val:
                texts.append(str(val))
        combined = expand_compound_words(" ".join(texts)).lower()
        score = 0.0
        for t in tokens:
            occ = combined.count(t.lower())
            if occ:
                df = token_doc_freq.get(t, len(leistungskatalog_dict))
                if df:
                    score += occ * (1.0 / df)
        if score > 0:
            scored.append((score, lkn_code))
    scored.sort(key=lambda x: x[0], reverse=True)
    if return_scores:
        return scored[:limit]
    return [code for _, code in scored[:limit]]
