import json
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

try:
    import faiss  # type: ignore[import]
except ModuleNotFoundError as exc:  # pragma: no cover - runtime guard
    raise SystemExit(
        "Das Paket 'faiss-cpu' ist erforderlich. Bitte führen Sie 'pip install faiss-cpu' aus."
    ) from exc

# --- Konfiguration ---
DATA_DIR = Path("data")
LEISTUNGSKATALOG_PATH = DATA_DIR / "LKAAT_Leistungskatalog.json"
FAISS_INDEX_FILE = DATA_DIR / "vektor_index.faiss"
FAISS_CODES_FILE = DATA_DIR / "vektor_index_codes.json"

# Leistungsfähiges, mehrsprachiges Modell
EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
# Token-Limit für längere Texte erhöhen
MAX_SEQ_LENGTH = 384


def get_embedding_text_for_entry(entry: dict) -> str:
    """Erstellt den Text, der für das Embedding eines Katalogeintrags verwendet wird."""
    parts: list[str] = []

    lkn = entry.get("LKN", "")
    typ = entry.get("Typ", "")
    if lkn:
        parts.append(f"LKN: {lkn}")
    if typ:
        parts.append(f"Typ: {typ}")

    for key in ["Beschreibung", "Beschreibung_f", "Beschreibung_i"]:
        if entry.get(key):
            parts.append(str(entry[key]))

    for key in [
        "MedizinischeInterpretation",
        "MedizinischeInterpretation_f",
        "MedizinischeInterpretation_i",
    ]:
        if entry.get(key):
            parts.append(str(entry[key]))

    return ". ".join(parts)


def main() -> None:
    """Generiert Embeddings und speichert FAISS-Index inklusive Code-Mapping."""
    import sys
    
    print("Starte Embedding-Generierung...", flush=True)
    
    if sys.version_info >= (3, 13):
        print("\n" + "!" * 60)
        print("WARNUNG: Sie verwenden Python 3.13.")
        print("Diese Version hat bekannte Inkompatibilitäten mit 'sentence-transformers' und 'torch'.")
        print("Das Programm könnte beim Laden des Modells abstürzen oder hängen bleiben.")
        print("EMPFOHLENE LÖSUNG: Installieren Sie die Nightly-Version von PyTorch:")
        print("pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cpu")
        print("!" * 60 + "\n", flush=True)

    start_time = time.time()

    print(f"Lade Leistungskatalog von: {LEISTUNGSKATALOG_PATH}", flush=True)
    try:
        with open(LEISTUNGSKATALOG_PATH, "r", encoding="utf-8") as f:
            leistungskatalog = json.load(f)
        print(f"Leistungskatalog mit {len(leistungskatalog)} Einträgen geladen.", flush=True)
    except FileNotFoundError:
        print(f"FEHLER: Leistungskatalog-Datei nicht gefunden unter {LEISTUNGSKATALOG_PATH}", flush=True)
        return
    except json.JSONDecodeError:
        print(f"FEHLER: Ungültiges JSON in {LEISTUNGSKATALOG_PATH}", flush=True)
        return

    print(f"Lade Embedding-Modell: {EMBEDDING_MODEL_NAME}", flush=True)
    try:
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        model.max_seq_length = MAX_SEQ_LENGTH
        print("Modell erfolgreich geladen.", flush=True)
    except Exception as exc:
        print(f"FEHLER beim Laden des Modells: {exc}", flush=True)
        return

    print("Bereite Texte für das Embedding vor...", flush=True)
    texts_to_embed: list[str] = []
    lkn_codes: list[str] = []
    for entry in leistungskatalog:
        if isinstance(entry, dict) and entry.get("LKN"):
            texts_to_embed.append(get_embedding_text_for_entry(entry))
            lkn_codes.append(str(entry["LKN"]))
    print(f"{len(texts_to_embed)} Texte vorbereitet.", flush=True)

    if not texts_to_embed:
        print("WARNUNG: Keine gültigen Einträge gefunden.", flush=True)
        return

    print("Generiere Embeddings (dies kann einige Minuten dauern)...", flush=True)
    try:
        embeddings = model.encode(
            texts_to_embed,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        print(f"Embeddings generiert. Shape: {embeddings.shape}", flush=True)
    except Exception as exc:
        print(f"FEHLER bei der Generierung der Embeddings: {exc}", flush=True)
        return

    print("Erstelle FAISS-Index...", flush=True)
    if embeddings.shape[0] == 0:
        print("WARNUNG: Keine Embeddings zum Indizieren vorhanden.", flush=True)
        return

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    vectors = embeddings.astype(np.float32)
    index.add(x=vectors)  # type: ignore[call-arg]  # Current faiss binding only expects the data array
    print(f"FAISS-Index mit {index.ntotal} Vektoren erstellt.", flush=True)

    print(f"Speichere FAISS-Index nach: {FAISS_INDEX_FILE}", flush=True)
    FAISS_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(FAISS_INDEX_FILE))

    print(f"Speichere LKN-Code-Liste nach: {FAISS_CODES_FILE}", flush=True)
    with FAISS_CODES_FILE.open("w", encoding="utf-8") as f:
        json.dump(lkn_codes, f, ensure_ascii=False, indent=2)

    duration = time.time() - start_time
    print("\nVerarbeitung abgeschlossen.", flush=True)
    print(f"Gesamtdauer: {duration:.2f} Sekunden.", flush=True)
    print(f"Dateien erfolgreich erstellt:\n- {FAISS_INDEX_FILE}\n- {FAISS_CODES_FILE}", flush=True)


if __name__ == "__main__":
    main()
