# -*- coding: utf-8 -*-
"""server.py – Flask backend mit lokaler Chroma‑Suche
=====================================================
Dieses Backend
* nutzt **Sentence‑Transformer**‑Embeddings (CPU) und **ChromaDB** für semantisches
  Retrieval aus dem TARDOC‑Leistungskatalog (./chroma‑Ordner, via build_index.py).
* stellt einen Endpunkt /api/analyze-billing bereit, der:
    1. den Freitext des Nutzers semantisch sucht (Top‑40 Zeilen, Token‑Limit)
    2. den kompakten Kontext an ein OpenAI‑Chat‑Modell sendet (JSON‑Antwort)
    3. optional die LKN über regelpruefer.py validiert.

Voraussetzungen
---------------
    pip install flask chromadb sentence-transformers tiktoken python-dotenv pandas openai

Vor dem ersten Start `python build_index.py` ausführen, um den Chroma‑Index zu
befüllen (siehe separates Skript).
"""
from __future__ import annotations

import os
import json
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from flask import Flask, request, jsonify, send_from_directory, abort
from dotenv import load_dotenv

import chromadb
from sentence_transformers import SentenceTransformer
import tiktoken

try:
    import regelpruefer
except ImportError:
    regelpruefer = None  # Regelprüfung bleibt optional

# ── Konfiguration ──────────────────────────────────────────────────────────
load_dotenv()
print("DEBUG key:", os.getenv("OPENAI_API_KEY")[:8], "…")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MODEL_CTX    = 16385 if "3.5" in OPENAI_MODEL else 128000
MAX_PROMPT   = MODEL_CTX - 2000          # Puffer für Header + Antwort

EMB_MODEL  = "all-mpnet-base-v2"
CHROMA_DIR = "chroma"
COLL_NAME  = "tardoc"

SYSTEM_ROLE = "Du bist ein Schweizer TARDOC‑Abrechnungs‑Assistent."
SCHEMA_JSON = (
    '{\n  "identified_leistungen": [],'    # JSON‑Schema als kompaktes Literal
    '\n  "extracted_info": {"dauer_minuten":0,"menge":0,'
    '"alter":0,"geschlecht":"unbekannt"},'
    '\n  "begruendung_llm": ""\n}'
)

# ── Initialisierung ───────────────────────────────────────────────────────
app = Flask(__name__, static_folder=".", static_url_path="")

print("Lade Sentence‑Transformer …")
st_model = SentenceTransformer(EMB_MODEL)
print("Öffne ChromaDB …")
client   = chromadb.PersistentClient(path=CHROMA_DIR)
col      = client.get_collection(COLL_NAME)
enc      = tiktoken.encoding_for_model(OPENAI_MODEL)

# Daten für UI‑Lookups, Regelprüfung und semantische Fallback-Suche
leistungskatalog_data: List[Dict[str, Any]] = []
regelwerk_dict: Dict[str, Any] = {}
# Zusätzliche Daten für Pauschalen- und TARDOC-Berechnung
pauschale_lp_data: List[Dict[str, Any]] = []
pauschalen_data: List[Dict[str, Any]] = []
pauschale_bedingungen_data: List[Dict[str, Any]] = []
tardoc_tarifpositionen_data: List[Dict[str, Any]] = []
tabellen_data: List[Dict[str, Any]] = []
# Globale Kontextdaten für den aktuellen Abrechnungsfall (gesetzt in analyze_billing)
billing_context: Dict[str, Any] = {}
# Dokumente für semantische Fallback-Suche (Bezeichnung + Interpretation)
tardoc_doc_map: Dict[str, str] = {}
tardoc_doc_texts: List[str] = []

# ── Daten laden (für UI‑Lookups / Regelprüfung) ───────────────────────────
DATA_DIR = Path("data")

def load_data() -> None:
    global leistungskatalog_data, regelwerk_dict
    global pauschale_lp_data, pauschalen_data, pauschale_bedingungen_data
    global tardoc_tarifpositionen_data, tabellen_data
    try:
        with open(DATA_DIR / "tblLeistungskatalog.json", encoding="utf-8") as f:
            leistungskatalog_data = json.load(f)
        print(f"✓ Leistungskatalog {len(leistungskatalog_data)} Einträge geladen")
    except FileNotFoundError:
        print("⚠️  Leistungskatalog fehlt – Beschreibungs‑Lookups deaktiviert")
        leistungskatalog_data = []

    if regelpruefer:
        regel_json = DATA_DIR / "strukturierte_regeln_komplett.json"
        regelwerk_dict = regelpruefer.lade_regelwerk(str(regel_json))
        print(f"✓ Regelwerk {len(regelwerk_dict)} LKNs geladen")
    else:
        regelwerk_dict = {}
        print("ℹ️  Regelprüfung deaktiviert")
    # Pauschalen-Daten laden
    try:
        with open(DATA_DIR / "tblPauschaleLeistungsposition.json", encoding="utf-8") as f:
            pauschale_lp_data = json.load(f)
        print(f"✓ Pauschale-Leistungspositionen {len(pauschale_lp_data)} Einträge geladen")
    except FileNotFoundError:
        pauschale_lp_data = []
        print("⚠️  tblPauschaleLeistungsposition.json nicht gefunden – Pauschalen-Zuordnung deaktiviert")
    try:
        with open(DATA_DIR / "tblPauschalen.json", encoding="utf-8") as f:
            pauschalen_data = json.load(f)
        print(f"✓ Pauschalen {len(pauschalen_data)} Einträge geladen")
    except FileNotFoundError:
        pauschalen_data = []
        print("⚠️  tblPauschalen.json nicht gefunden – Pauschalen-Daten deaktiviert")
    try:
        with open(DATA_DIR / "tblPauschaleBedingungen.json", encoding="utf-8") as f:
            pauschale_bedingungen_data = json.load(f)
        print(f"✓ Pauschalen-Bedingungen {len(pauschale_bedingungen_data)} Einträge geladen")
    except FileNotFoundError:
        pauschale_bedingungen_data = []
        print("⚠️  tblPauschaleBedingungen.json nicht gefunden – Bedingungsprüfung deaktiviert")
    # TARDOC-Tarifpositionen laden
    # TARDOC-Tarifpositionen laden und semantische Fallback-Dokumente aufbauen
    try:
        with open(DATA_DIR / "TARDOCGesamt_optimiert_Tarifpositionen.json", encoding="utf-8") as f:
            tardoc_tarifpositionen_data = json.load(f)
        print(f"✓ TARDOC-Tarifpositionen {len(tardoc_tarifpositionen_data)} Einträge geladen")
        # Aufbau von Dokumenttexten für einfache Substring-Suche
        tardoc_doc_map.clear()
        tardoc_doc_texts.clear()
        for e in tardoc_tarifpositionen_data:
            lkn = e.get("LKN") or ""
            bezeichnung = e.get("Bezeichnung") or ""
            interpretation = e.get("Interpretation") or ""
            text = bezeichnung
            if interpretation:
                text = f"{text}. {interpretation}"
            doc = f"{lkn} – {text}"
            tardoc_doc_map[lkn] = doc
            tardoc_doc_texts.append(doc)
        # Leistungskatalog (Beschreibung) einbeziehen
        for e in leistungskatalog_data:
            code = e.get("LKN") or ""
            desc = e.get("Beschreibung") or ""
            doc = f"{code} – {desc}"
            tardoc_doc_map[code] = doc
            tardoc_doc_texts.append(doc)
        # Pauschalen (Pauschale_Text) einbeziehen
        for e in pauschalen_data:
            code = e.get("Pauschale") or ""
            text = e.get("Pauschale_Text") or ""
            doc = f"{code} – {text}"
            tardoc_doc_map[code] = doc
            tardoc_doc_texts.append(doc)
        print(f"✓ Semantische Fallback-Dokumente: {len(tardoc_doc_texts)} Einträge (Tarifpositionen + LKN + Pauschalen)")
    except FileNotFoundError:
        tardoc_tarifpositionen_data = []
        print("⚠️  TARDOCGesamt_optimiert_Tarifpositionen.json nicht gefunden – Einzelleistungs-Berechnung limitiert")
    # Tabellen (ICD, GTIN, service_catalog) laden
    try:
        with open(DATA_DIR / "tblTabellen.json", encoding="utf-8") as f:
            tabellen_data = json.load(f)
        print(f"✓ tblTabellen {len(tabellen_data)} Einträge geladen")
    except FileNotFoundError:
        tabellen_data = []
        print("⚠️  tblTabellen.json nicht gefunden – externe Referenzen limitiert")

# ── Semantischer Kontext ─────────────────────────────────────────────────
TOKEN_PER_CHAR = 0.25  # grobe Schätzung 4 Zeichen ≈ 1 Token

def semantic_context(query: str, k: int = 80, cap: int = int(MAX_PROMPT * 0.75)) -> str:
    """Top‑k ähnliche Zeilen plus substring-basierte Fallback-Treffer unter Token‑Budget liefern."""
    # Semantische Suche
    q_vec = st_model.encode([query], normalize_embeddings=True)
    # Hybrid Dense + Lexical Retrieval (semantisch + BM25-ähnlich)
    res = col.query(
        query_embeddings=q_vec,
        query_texts=[query],
        n_results=k,
        include=["documents"]
    )
    sem_docs = res.get("documents", [[]])[0]
    lines: List[str] = []
    used = 0
    # Fallback: Substring-Suche nach signifikanten Query-Wörtern (häufige Begriffe ignorieren)
    words = [w.lower() for w in query.split() if len(w) >= 4]
    # Häufigkeit der Wörter in den Dokumenten berechnen
    freqs: Dict[str, int] = {}
    for w in words:
        # Zähle Vorkommen als Substring in docs
        freqs[w] = sum(1 for doc in tardoc_doc_texts if w in doc.lower())
    # Nur seltene Wörter (max. Kapazität) verwenden, sonst auf Original-Liste zurückgreifen
    max_freq = 100
    sig_words = [w for w in words if freqs.get(w, 0) <= max_freq]
    fb_words = sig_words or words
    # Fallback-Dokumente sammeln (in Reihenfolge der Begriffe)
    fallback: List[str] = []
    for w in fb_words:
        for doc in tardoc_doc_texts:
            if w in doc.lower() and doc not in fallback:
                fallback.append(doc)
    # Fallback-Dokumente zuerst aufnehmen (unter Token-Limit)
    for doc in fallback:
        est = math.ceil(len(doc) * TOKEN_PER_CHAR) + 4
        if used + est > cap:
            break
        lines.append(doc)
        used += est
    # Dann semantische Treffer, sofern noch Platz und nicht dupliziert
    for doc in sem_docs:
        if doc in lines:
            continue
        est = math.ceil(len(doc) * TOKEN_PER_CHAR) + 4
        if used + est > cap:
            break
        lines.append(doc)
        used += est
    return "\n".join(lines)

# ── Prompt & LLM‑Aufruf ───────────────────────────────────────────────────
import openai
# Setup OpenAI client for v1 vs. legacy API
if hasattr(openai, "OpenAI"):
    # openai>=1.0.0
    llm_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    use_v1 = True
# else: openai<1.0.0 (legacy API)
else:
    # openai<1.0.0 (legacy API)
    openai.api_key = os.getenv("OPENAI_API_KEY")
    llm_client = openai
    use_v1 = False
# Determine proper RateLimitError exception class for OpenAI
try:
    # preferred location for exceptions
    from openai.error import RateLimitError as OpenAIRateLimitError # type: ignore
except (ImportError, ModuleNotFoundError, AttributeError):
    try:
        # fallback in newer client versions
        from openai.exceptions import RateLimitError as OpenAIRateLimitError # type: ignore
    except (ImportError, ModuleNotFoundError, AttributeError):
        OpenAIRateLimitError = None

def make_prompt(text: str, ctx: str) -> str:
    return (
        "Analysiere den folgenden medizinischen Behandlungstext.\n"
        f"--- Relevante TARDOC‑Zeilen ---\n{ctx}\n--- Ende ---\n"
        f"Gib ausschließlich JSON nach Schema:\n{SCHEMA_JSON}\n"
        f"Text: '{text}'\n\nJSON‑Antwort:"
    )

def call_llm(prompt: str) -> Dict[str, Any]:
    """Call the OpenAI chat model and parse JSON response."""
    # Ensure API key present
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY fehlt – setze in .env")
    # Prepare common parameters
    params = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system",  "content": SYSTEM_ROLE},
            {"role": "user",    "content": prompt}
        ],
        "max_tokens": 1500,
        "temperature": 0.2,
    }
    # Call API depending on client version
    if use_v1:
        # openai>=1.0: operations API
        resp = llm_client.chat.completions.create(**params)
        # Convert to dict if necessary
        try:
            data = resp.to_dict()
        except Exception:
            data = resp
    else:
        # legacy openai<1.0
        resp = llm_client.ChatCompletion.create(**params)
        data = resp
    # Extract assistant content
    try:
        content = data['choices'][0]['message']['content']
    except Exception as e:
        raise ValueError(f"Unerwartetes Format der LLM-Antwort: {e}\nAntwort-Rohdaten: {data}")
    # Parse JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Fehler beim Parsen der LLM-Antwort als JSON: {e}\nAntwort: {content}")

# ── Regelprüfung (Wrapper) ───────────────────────────────────────────────

def check_rules(
    lkn: str | None,
    menge: int,
    icds: list[str],
    begleit_lkns: list[str] | None = None,
    pauschalen: list[str] | None = None,
) -> Dict[str, Any]:
    """Wrapper zur Prüfung von Regeln, inkl. Kontext anderer Leistungen."""
    if not lkn:
        return {"abrechnungsfaehig": False, "fehler": ["Keine LKN"]}
    # Wenn Regelprüfung deaktiviert, Leistungen als abrechnungsfähig markieren
    if not regelpruefer or not regelwerk_dict:
        return {"abrechnungsfaehig": True, "fehler": []}
    # Basis-Abrechnungsfall aufbauen
    fall: Dict[str, Any] = {
        "LKN": lkn,
        "Menge": menge,
        "ICD": icds,
        "Begleit_LKNs": begleit_lkns or [],
        "Pauschalen": pauschalen or []
    }
    # Kontext (Alter, Geschlecht, GTIN) ergänzen, falls vorhanden
    if billing_context.get("alter") is not None:
        fall["Alter"] = billing_context["alter"]
    if billing_context.get("geschlecht"):
        fall["Geschlecht"] = billing_context["geschlecht"]
    if billing_context.get("gtins"):
        fall["GTIN"] = billing_context["gtins"]
    return regelpruefer.pruefe_abrechnungsfaehigkeit(fall, regelwerk_dict)
    
# ── Berechnung von Pauschalen und Einzelleistungen ────────────────────────
def calculate_pauschale(lkn: str, menge: int, icds: list[str], identified: list[str]) -> Optional[Dict[str, Any]]:
    # Direkter Pauschalen-Trigger, wenn LKN selbst Pauschale ist
    direct = any(p.get("Pauschale") == lkn for p in pauschalen_data)
    if direct:
        candidates = [lkn]
    else:
        candidates = list({e.get("Pauschale") for e in pauschale_lp_data if e.get("Leistungsposition") == lkn})
    if not candidates:
        return None
    # Finde Pauschalen-Daten und wähle die mit minimalen Taxpunkten
    options = [p for p in pauschalen_data if p.get("Pauschale") in candidates]
    if not options:
        return None
    # Wähle die Pauschale mit den minimalen Taxpunkten (None-Werte als unendlich behandeln)
    def _taxpunkte_value(p: dict) -> float:
        v = p.get("Taxpunkte")
        # Falls kein numerischer Wert vorhanden, als unendlich werten
        return v if isinstance(v, (int, float)) else float('inf')
    selected = min(options, key=_taxpunkte_value)
    pauschale_code = selected.get("Pauschale")
    # Bedingungen prüfen (ICD, LKN, Medikation)
    conds = [c for c in pauschale_bedingungen_data if c.get("Pauschale") == pauschale_code]
    if conds:
        # Gruppierte Prüfung: Bedingungen pro Gruppe kombinieren
        group_results: Dict[int, bool] = {}
        # Kontextdaten
        icd_list = icds or []
        ident_lkns = [i.get("lkn") if isinstance(i, dict) else i for i in identified]
        gtins = billing_context.get("gtins", []) or []
        # Bedingungen auswerten
        for cond in conds:
            grp = cond.get("Gruppe")
            op = cond.get("Operator")
            ctype = cond.get("Bedingungstyp") or ""
            # Werte (ggf. kommagetrennt)
            vals = [v.strip() for v in str(cond.get("Werte", "")).split(",") if v.strip()]
            cond_val = False
            if ctype == "HAUPTDIAGNOSE IN TABELLE":
                # ICD aus Tabellen prüfen
                for tbl in vals:
                    codes = [e.get("Code") for e in tabellen_data
                             if e.get("Tabelle") == tbl and e.get("Tabelle_Typ") == "icd"]
                    if any(ic in icd_list for ic in codes):
                        cond_val = True
                        break
            elif ctype == "LEISTUNGSPOSITIONEN IN LISTE":
                if any(v in ident_lkns for v in vals):
                    cond_val = True
            elif ctype == "LEISTUNGSPOSITIONEN IN TABELLE" or ctype == "TARIFPOSITIONEN IN TABELLE":
                for tbl in vals:
                    codes = [e.get("Code") for e in tabellen_data
                             if e.get("Tabelle") == tbl and e.get("Tabelle_Typ") == "service_catalog"]
                    if any(c in ident_lkns for c in codes):
                        cond_val = True
                        break
            elif ctype == "MEDIKAMENTE IN LISTE":
                if any(v in gtins for v in vals):
                    cond_val = True
            else:
                # Andere Bedingungstypen ignoriere (als erfüllt annehmen)
                cond_val = True
            # Kombiniere in Gruppe
            if grp not in group_results:
                group_results[grp] = cond_val
            else:
                if op == "UND":
                    group_results[grp] = group_results[grp] and cond_val
                else:
                    group_results[grp] = group_results[grp] or cond_val
        # Falls keine Gruppe erfüllt, Pauschale nicht anwendbar
        if not any(group_results.values()):
            return None
    # Taxpunkte ermitteln (None oder Nicht-Zahl als 0 behandeln)
    _tp_val = selected.get("Taxpunkte")
    tp = _tp_val if isinstance(_tp_val, (int, float)) else 0.0
    return {
        "pauschale": pauschale_code,
        "taxpunkte_per_unit": tp,
        "sum_taxpunkte": tp * menge,
        "abrechnungsfaehig": True,
        "fehler": []
    }

def calculate_einzelleistung(
    lkn: str,
    menge: int,
    icds: list[str],
    begleit_lkns: list[str] | None = None,
    pauschalen: list[str] | None = None,
) -> Dict[str, Any]:
    # Suche Tarifposition in TARDOC-Daten
    entry = next((e for e in tardoc_tarifpositionen_data if e.get("LKN") == lkn), None)
    al = entry.get("AL_(normiert)") if entry and entry.get("AL_(normiert)") is not None else 0.0
    ipl = entry.get("IPL_(normiert)") if entry and entry.get("IPL_(normiert)") is not None else 0.0
    sum_tp = (al + ipl) * menge
    # Regelprüfung (z.B. Kumulations- und Mengenbeschränkungen) mit Kontext
    rule = check_rules(lkn, menge, icds, begleit_lkns=begleit_lkns, pauschalen=pauschalen)
    return {
        "al": al,
        "ipl": ipl,
        "sum_taxpunkte": sum_tp,
        "abrechnungsfaehig": rule.get("abrechnungsfaehig", False),
        "fehler": rule.get("fehler", [])
    }

# ── Flask‑API / Analyse‑Endpunkt ──────────────────────────────────────────
@app.route("/api/analyze-billing", methods=["POST"])
def analyze_billing():
    if not request.is_json:
        return jsonify({"error": "JSON erwartet"}), 400

    text = (request.json.get("inputText") or "").strip()
    icds = request.json.get("icd", [])
    if not text:
        return jsonify({"error": "inputText fehlt"}), 400

    # Kontext für semantische Suche und LLM-Aufruf
    ctx = semantic_context(text)
    try:
        llm = call_llm(make_prompt(text, ctx))
    except Exception as e:
        # Handle OpenAI rate-limiting if exception class is available
        if OpenAIRateLimitError is not None and isinstance(e, OpenAIRateLimitError):
            return jsonify({"error": "OpenAI-API-Kontingent überschritten. Bitte prüfen Sie Plan und Abrechnungsdetails."}), 429
        app.logger.error("Fehler beim LLM-Aufruf: %s", e)
        return jsonify({"error": f"Fehler beim LLM-Aufruf: {e}"}), 500
    # Kontextdaten für Pauschalen- und Regelprüfung speichern
    billing_context["icds"] = icds or []
    extracted = llm.get("extracted_info", {}) or {}
    # Alter und Geschlecht aus LLM-Extraktion (falls vorhanden)
    try:
        billing_context["alter"] = int(extracted.get("alter", 0) or 0)
    except Exception:
        billing_context["alter"] = 0
    billing_context["geschlecht"] = extracted.get("geschlecht") or None
    # Medikamenten-GTINs aus Anfrage (optional)
    billing_context["gtins"] = request.json.get("gtin", []) or []

    # Fallback: größerer Kontext, falls keine LKN erkannt
    # Fallback: größerer Kontext, falls keine LKN erkannt
    if not llm.get("identified_leistungen"):
        ctx_big = semantic_context(text, k=80, cap=int(MAX_PROMPT * 0.75))
        try:
            llm = call_llm(make_prompt(text, ctx_big))
        except Exception as e:
            # Handle OpenAI rate-limiting in fallback if exception class is available
            if OpenAIRateLimitError is not None and isinstance(e, OpenAIRateLimitError):
                return jsonify({"error": "OpenAI-API-Kontingent überschritten. Bitte prüfen Sie Plan und Abrechnungsdetails."}), 429
            app.logger.error("Fehler beim LLM-Aufruf (Fallback): %s", e)
            return jsonify({"error": f"Fehler beim LLM-Aufruf (Fallback): {e}"}), 500
    # Semantische Fallback-Kandidaten, wenn LLM weiterhin keine LKN liefert
    if not llm.get("identified_leistungen"):
        # Top-10 Kandidaten aus semantischer Suche
        docs_fb = semantic_context(text, k=10, cap=int(MAX_PROMPT * 0.25))
        codes = []
        for line in docs_fb.split("\n"):
            parts = line.split("–", 1)
            if parts and parts[0].strip():
                codes.append(parts[0].strip())
        # Ersetze identifizierte Leistungen durch Fallback-Codes
        llm["identified_leistungen"] = codes
        llm["begruendung_llm"] = f"Semantische Fallback-Kandidaten: {', '.join(codes)}"

    # Extrahierte Infos (z.B. Dauer in Minuten)
    extracted = llm.get("extracted_info", {}) or {}
    duration = int(extracted.get("dauer_minuten", 0) or 0)
    # Default Menge: Dauer (Minuten) oder 1
    menge_req = duration if duration > 0 else 1
    results: list[dict] = []
    # Fallback für zeitabhängige Konsultation: nur wenn Text nach Konsultation klingt (deaktiviert)
    text_low = text.lower()
    # if duration > 0 and "konsult" in text_low:
    if False:  # Konsultations-Logik deaktiviert
        # Kandidaten für Basisleistungen (erste 5 Min. Konsultation)
        basis_cands = [e for e in tardoc_tarifpositionen_data
                       if e.get("Zeit_LieS") == 5.0
                          and "erste" in e.get("Bezeichnung", "").lower()
                          and "konsultation" in e.get("Bezeichnung", "").lower()]
        basis = None
        # Wähle spezifisch nach Textinhalt
        if "hausarzt" in text_low:
            basis = next((e for e in basis_cands if "hausärzt" in e.get("Bezeichnung", "").lower()), None)
        elif "telemedizin" in text_low:
            basis = next((e for e in basis_cands if "telemedizin" in e.get("Bezeichnung", "").lower()), None)
        # Fallback allgemein
        if not basis:
            basis = next((e for e in basis_cands if "ärztliche" in e.get("Bezeichnung", "").lower()), None)
        # Zuschlagsleistung: jede weitere 1 Min.
        addon = None
        if basis:
            addon = next((e for e in tardoc_tarifpositionen_data
                           if e.get("Typ") == "Z"
                              and e.get("Parent", "").startswith(basis.get("LKN", ""))), None)
        # Basisleistung abrechnen
        if basis:
            res1 = calculate_einzelleistung(basis.get("LKN"), 1, icds)
            results.append({"typ": "Einzelleistung", "lkn": basis.get("LKN"), "menge": 1, **res1})
        # Zuschlagsleistung abrechnen (dauer - Basiszeit, max. 15)
        extra = 0
        if addon and basis:
            raw_extra = max(0, duration - (basis.get("Zeit_LieS", 0)))
            # Maximal 15 weitere Einheiten zulässig
            extra = min(raw_extra, 15)
            if extra > 0:
                base_lkn = basis.get("LKN")
                # Surcharge with context of basis LKN
                res2 = calculate_einzelleistung(
                    addon.get("LKN"), extra, icds,
                    begleit_lkns=[base_lkn] if base_lkn else None
                )
                # Wenn ursprünglich mehr Einheiten erfasst wurden, fügen wir Hinweis hinzu
                if raw_extra > extra:
                    res2.setdefault("fehler", []).append(
                        f"Maximale Zusatzmenge von {extra} überschritten (Angefragt: {raw_extra})"
                    )
                results.append({"typ": "Einzelleistung", "lkn": addon.get("LKN"), "menge": extra, **res2})
        # LLM-Analysierte Kodes anzeigen
        identified = []
        if basis:
            identified.append({"lkn": basis.get("LKN"), "menge": 1})
        if addon and extra > 0:
            identified.append({"lkn": addon.get("LKN"), "menge": extra})
        llm["identified_leistungen"] = identified
        return jsonify({"llm_ergebnis": llm, "leistungen": results})
    # Sonstige Leistungen: LLM-basierte Identifikation
    identified = llm.get("identified_leistungen") or []
    # Ergänze LKN aus Begründung, falls vergessen
    codes_from_text = re.findall(r'\b[A-Z]{2}\.d{2}\.d{4}\b', llm.get("begruendung_llm", ""))
    # Korrekte Extraktion der LKNs aus Begründung (Behebung fehlerhafter Pattern)
    codes_from_text = re.findall('[A-Z]{2}[.][0-9]{2}[.][0-9]{4}', llm.get("begruendung_llm", ""))
    for code in codes_from_text:
        if not any((isinstance(i, dict) and i.get("lkn") == code) or (isinstance(i, str) and i == code) for i in identified):
            # Verwende extrahierte Menge oder Standardmenge
            qty = extracted.get("menge") if isinstance(extracted.get("menge"), int) and extracted.get("menge") > 0 else 1
            identified.append({"lkn": code, "menge": qty})
    # Durchlaufe identifizierte Leistungen
    for item in identified:
        # LKN extrahieren
        if isinstance(item, str):
            lkn = item
        else:
            lkn = item.get("lkn")
        # Menge aus LLM oder global
        if isinstance(item, dict) and item.get("menge") is not None:
            try:
                item_menge = int(item.get("menge"))
            except Exception:
                item_menge = menge_req
        else:
            item_menge = menge_req
        # Typ aus Katalog bestimmen
        cat = next((e for e in leistungskatalog_data if e.get("LKN") == lkn), {})
        typ_code = cat.get("Typ")
        if typ_code in ("P", "PZ"):
            pausch = calculate_pauschale(lkn, item_menge, icds, identified)
            if pausch:
                entry = {"typ": "Pauschale", "lkn": lkn, "menge": item_menge, **pausch}
            else:
                entry = {"typ": "Einzelleistung", "lkn": lkn, "menge": item_menge, **calculate_einzelleistung(lkn, item_menge, icds)}
        else:
            entry = {"typ": "Einzelleistung", "lkn": lkn, "menge": item_menge, **calculate_einzelleistung(lkn, item_menge, icds)}
        results.append(entry)
    # Priorisieren: Umfassende rheumatologische Untersuchung (KF.05.0050)
    if any(item.get("lkn") == "KF.05.0050" for item in results):
        # Hauptleistung extrahieren
        primary = next(item for item in results if item.get("lkn") == "KF.05.0050")
        # Vorschläge für regelkonforme Zusatzleistungen
        additional_codes = ["KF.05.0040", "KF.00.0030", "GK.30.0030", "GK.25.0170"]
        suggestions = []
        for code in additional_codes:
            svc = calculate_einzelleistung(code, 1, icds)
            if svc.get("abrechnungsfaehig"):
                # Beschreibung aus Tarifdaten
                desc = next((e.get("Bezeichnung") for e in tardoc_tarifpositionen_data if e.get("LKN") == code), "")
                suggestions.append({
                    "lkn": code,
                    "beschreibung": desc,
                    "al": svc.get("al"),
                    "ipl": svc.get("ipl"),
                    "sum_taxpunkte": svc.get("sum_taxpunkte"),
                    "abrechnungsfaehig": True,
                    "fehler": []
                })
        return jsonify({
            "llm_ergebnis": llm,
            "primary_service": primary,
            "message": "Möchten Sie weitere Leistungen hinzufügen?",
            "additional_services": suggestions
        })
    # Standard-Antwort: alle ermittelten Leistungen
    return jsonify({"llm_ergebnis": llm, "leistungen": results})

# ── Static‑Routes & Start ────────────────────────────────────────────────
@app.route("/")
def index():
    load_data()
    return send_from_directory(".", "index.html")

@app.route("/files/<path:p>")
def static_files(p: str):
    if p.startswith(".") or p in {"server.py", ".env"}:
        abort(404)
    return send_from_directory(".", p)
try:
    from server_integration import integrate_hybrid_recognizer
    import sys

    # Integration des HybridRecognizer – ersetzt analyze_billing durch eine verbesserte Version
    app = integrate_hybrid_recognizer(app, sys.modules[__name__])
    print("⚡ HybridRecognizer integriert")
except ImportError:
    print("⚠️ server_integration.py nicht gefunden; Standard-Server ohne Hybrid-Erkenner")

if __name__ == "__main__":
    load_data()
    print("🚀  Server läuft → http://127.0.0.1:8000")
    app.run(host="127.0.0.1", port=8000, debug=True)
