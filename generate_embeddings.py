"""Erzeugt Satz-Embeddings fuer den Leistungskatalog.

Das Skript benoetigt das Paket ``sentence-transformers``. Es liest den
Leistungskatalog ein, kombiniert zentrale Beschreibungsfelder mit den
gepflegten Synonymen (inklusive aller verknuepften LKN-Codes) und berechnet
kompakte Vektor-Repraesentationen. Die resultierenden Embeddings werden als
JSON-Datei unter ``data/leistungskatalog_embeddings.json`` gespeichert. Die
Datei enthaelt zwei Schluessel:

* ``codes`` - Liste aller LKN-Codes in derselben Reihenfolge wie die Vektoren.
* ``embeddings`` - float16-kodierte Listen mit den berechneten Vektoren.

Beim Start des Backends werden diese Vektoren direkt von diesem Pfad geladen,
sodass keine erneute Berechnung notwendig ist. Damit dient die Datei als Cache
fuer die RAG-Suche und fuer Qualitaetstools.

Robustheit: Der Code erzwingt eine maximale Sequenzlaenge von 128 Tokens und
packt die Textteile budgetorientiert. Warnungen wie "Token indices sequence
length is longer than the specified maximum sequence length" werden damit
vermieden.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
from typing import Iterable

from synonyms.storage import load_synonyms

try:
    from sentence_transformers import SentenceTransformer
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore[assignment]

# -------------------- Konfiguration --------------------

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Harte Obergrenze fuer Tokenlaengen (MiniLM-L12-v2: 128)
HARD_MAX = 128

# Optional: harte Obergrenze fuer Synonyme pro LKN (None = unbegrenzt)
MAX_SYNONYMS_PER_LKN: int | None = 20

DATA_DIR = Path("data")
KATALOG_PATH = DATA_DIR / "LKAAT_Leistungskatalog.json"
OUT_PATH = DATA_DIR / "leistungskatalog_embeddings.json"
SYNONYMS_PATH = DATA_DIR / "synonyms.json"

# -------------------- Hilfsfunktionen --------------------


def load_katalog() -> list[dict]:
    with KATALOG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def force_hard_max(model) -> None:
    """Erzwingt HARD_MAX auf Model- und Tokenizer-Ebene – pylance-sicher via setattr()."""
    # SentenceTransformers-Objekt
    if hasattr(model, "max_seq_length"):
        setattr(model, "max_seq_length", HARD_MAX)

    # Manche ST-Versionen haben ein erstes Modul mit eigener max_seq_length
    try:
        first = getattr(model, "_first_module", None)
        fm = first() if callable(first) else None
    except Exception:
        fm = None
    if fm is not None and hasattr(fm, "max_seq_length"):
        setattr(fm, "max_seq_length", HARD_MAX)

    # HF-Tokenizer
    tok = getattr(model, "tokenizer", None)
    if tok is not None:
        if hasattr(tok, "model_max_length"):
            setattr(tok, "model_max_length", HARD_MAX)
        init_kwargs = getattr(tok, "init_kwargs", None)
        if isinstance(init_kwargs, dict):
            init_kwargs["model_max_length"] = HARD_MAX

def trim_text_final(text: str, tokenizer) -> str:
    """Trimmt den *finalen Gesamtstring* per HF-Tokenizer hart auf HARD_MAX."""
    enc = tokenizer(
        text,
        add_special_tokens=True,
        truncation=True,
        max_length=HARD_MAX,
        return_attention_mask=False,
        return_token_type_ids=False,
    )
    return tokenizer.decode(enc["input_ids"], skip_special_tokens=True).strip()


def token_len(tokenizer, text: str, with_specials: bool = True) -> int:
    """Tokenlaenge fuer *text* (nach finalem Trim sollte das <= HARD_MAX sein)."""
    return len(tokenizer.encode(text, add_special_tokens=with_specials))


def pack_under_budget(parts: Iterable[str], tokenizer) -> str:
    """
    Fuegt Teile nacheinander zusammen und schneidet *Teilstrings* bei Bedarf
    direkt per Tokenizer zu (truncation=True). Dadurch entstehen beim Packen
    keine Laengen-Warnungen mehr.
    """
    budget = max(0, HARD_MAX - 4)  # kleine Reserve fuer CLS/SEP/Separator
    if budget <= 0:
        return ""

    kept: list[str] = []
    used = 0
    first = True

    for p in parts:
        if not p:
            continue

        # Restbudget (Separator "~1 Token" grob mitrechnen)
        sep_cost = 0 if first else 1
        remaining = budget - used - sep_cost
        if remaining <= 0:
            break

        # *** WICHTIG: truncation=True + max_length=remaining ***
        ids = tokenizer.encode(
            p,
            add_special_tokens=False,
            truncation=True,
            max_length=max(remaining, 1),
        )
        if not ids:
            # nichts mehr sinnvoll unterzubringen
            break

        frag = tokenizer.decode(ids, skip_special_tokens=True).strip()
        if not frag:
            break

        # Jetzt passt der (ggf. beschnittene) Part sicher ins Budget
        kept.append(frag)
        used += len(ids) + sep_cost
        first = False

    return " | ".join(kept)


def truncate_text(text: str, tokenizer, max_tokens: int | None = None) -> str:
    """Trim *text* so that encoded length plus specials does not exceed ``max_tokens``.

    If ``max_tokens`` is ``None`` the tokenizer's ``model_max_length`` is used. The
    function operates purely on the tokenizer and does not add special tokens on
    output.
    """

    if max_tokens is None:
        max_tokens = getattr(tokenizer, "model_max_length", 0)
    allowance = max(0, max_tokens - tokenizer.num_special_tokens_to_add(False))
    ids = tokenizer.encode(text, add_special_tokens=False)
    if len(ids) <= allowance:
        return text
    trimmed = ids[:allowance]
    return tokenizer.decode(trimmed, clean_up_tokenization_spaces=True)


# -------------------- Hauptlogik --------------------


def main() -> None:
    import numpy as np

    if SentenceTransformer is None:  # pragma: no cover - runtime check
        raise SystemExit("The 'sentence-transformers' package is required to run this script")

    katalog = load_katalog()
    synonym_catalog = load_synonyms(SYNONYMS_PATH)

    model = SentenceTransformer(MODEL_NAME)
    force_hard_max(model)

    tokenizer = getattr(model, "tokenizer", None)
    if tokenizer is None:
        raise SystemExit("Model tokenizer not available; cannot enforce token budget.")

    # Synonyme je LKN sammeln
    synonyms_by_lkn: dict[str, set[str]] = defaultdict(set)
    for entry in synonym_catalog.entries.values():
        for code in getattr(entry, "lkns", []) or []:
            code_norm = str(code).strip().upper()
            if not code_norm:
                continue
            if entry.base_term:
                synonyms_by_lkn[code_norm].add(str(entry.base_term))
            for synonym in getattr(entry, "synonyms", []):
                if synonym:
                    synonyms_by_lkn[code_norm].add(str(synonym))

    codes: list[str] = []
    texts: list[str] = []

    for entry in katalog:
        raw_code = entry.get("LKN")
        if not raw_code:
            continue
        code = str(raw_code).strip().upper()

        # 1) Kernfelder (Beschreibung zuerst, dann medizinische Interpretation)
        base_parts: list[str] = []
        for key in [
            "Beschreibung",
            "Beschreibung_f",
            "Beschreibung_i",
            "MedizinischeInterpretation",
            "MedizinischeInterpretation_f",
            "MedizinischeInterpretation_i",
        ]:
            val = entry.get(key)
            if val:
                base_parts.append(str(val))

        # 2) Synonyme (deterministisch sortiert; optional limitieren)
        syns_set = synonyms_by_lkn.get(code, set())
        syns_sorted = sorted(syns_set)
        if MAX_SYNONYMS_PER_LKN is not None and MAX_SYNONYMS_PER_LKN >= 0:
            syns_sorted = syns_sorted[:MAX_SYNONYMS_PER_LKN]

        # 3) Teile kombinieren, Duplikate entfernen (ordnungsstabil)
        combined_parts = list(dict.fromkeys(base_parts + syns_sorted))
        if not combined_parts:
            continue

        # 4) Budget-orientiertes Packen MIT truncation (keine Warnungen)
        packed = pack_under_budget(combined_parts, tokenizer)
        if not packed:
            # Fallback: nimm das erste nicht-leere Feld, hart kuerzen
            head = next((p for p in combined_parts if p), "")
            if not head:
                continue
            packed = trim_text_final(head, tokenizer)

        # 5) Finalen Gesamtstring bauen (Code vorne dran) und HART trimmen
        text = f"{code} {packed}"
        text = trim_text_final(text, tokenizer)

        # 6) Verifikation; Notfall-Hartschnitt (sollte nicht mehr triggern)
        if token_len(tokenizer, text, with_specials=True) > HARD_MAX:
            ids = tokenizer.encode(text, add_special_tokens=True)[:HARD_MAX]
            text = tokenizer.decode(ids, skip_special_tokens=True).strip()

        codes.append(code)
        texts.append(text)

    # Letzte Sicherheitskontrolle vor dem Encode
    max_len_before = max((token_len(tokenizer, t, with_specials=True) for t in texts), default=0)
    print(f"Max token length before encode: {max_len_before} (limit {HARD_MAX})")

    print(f"Generating embeddings for {len(codes)} entries (max {HARD_MAX} tokens each)...")
    embeddings = model.encode(
        texts,
        show_progress_bar=True,
        convert_to_numpy=True,
        batch_size=64,
    )

    print(f"Generated {len(codes)} embeddings. Quantizing to float16...")
    embeddings_fp16 = embeddings.astype(np.float16)

    payload = {"codes": codes, "embeddings": embeddings_fp16.tolist()}
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"Wrote {len(codes)} embeddings to {OUT_PATH}")


if __name__ == "__main__":  # pragma: no cover - manual tool
    main()
