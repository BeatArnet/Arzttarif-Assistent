import os
import json
import re
from pathlib import Path
from typing import List, Dict

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from collections import Counter
from tqdm import tqdm  # Fortschrittsanzeige

# ── Konfiguration ──────────────────────────────────────────────────────────────
DATA_DIR = "data"
CHUNK_SIZE = 300
OVERLAP = int(CHUNK_SIZE * 0.15)
MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
COLLECTION_NAME = "tardoc"
CHROMA_DIR = "chroma"

# ── Initialisierung ────────────────────────────────────────────────────────────
model = SentenceTransformer(MODEL_NAME)
embedding_function = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
client = chromadb.PersistentClient(path=CHROMA_DIR)

# Vorhandene Collection löschen
try:
    client.delete_collection(COLLECTION_NAME)
except Exception:
    pass
col = client.create_collection(name=COLLECTION_NAME, embedding_function=embedding_function)

# ── Hilfsfunktionen ────────────────────────────────────────────────────────────
def flatten_record(rec: dict) -> str:
    parts = []
    for k, v in rec.items():
        if not v:
            continue
        if isinstance(v, list):
            if all(isinstance(i, dict) for i in v):
                parts.append(f"{k}: " + "; ".join(", ".join(f"{sk}:{sv}" for sk, sv in i.items()) for i in v))
            else:
                parts.append(f"{k}: {', '.join(map(str, v))}")
        else:
            parts.append(f"{k}: {v}")
    return ". ".join(parts)

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> List[str]:
    tokens = text.split()
    if len(tokens) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunks.append(" ".join(tokens[start:end]))
        if end >= len(tokens):
            break
        start = end - overlap
    return chunks

# ── Chunks vorbereiten ─────────────────────────────────────────────────────────
all_ids, all_docs, all_meta = [], [], []
files = [f for f in os.listdir(DATA_DIR) if f.endswith(".json")]

for file in tqdm(files, desc="Dateien werden verarbeitet"):
    path = os.path.join(DATA_DIR, file)
    try:
        with open(path, encoding="utf-8") as f:
            content = json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden {file}: {e}")
        continue

    base = os.path.splitext(file)[0]
    records = content if isinstance(content, list) else next((v for v in content.values() if isinstance(v, list)), [])
    if not records:
        continue

    for idx, rec in enumerate(tqdm(records, desc=f"{file}", leave=False)):
        if not isinstance(rec, dict):
            continue
        rec_id = rec.get("LKN") or rec.get("Kapitel") or rec.get("GI_Nr") or str(idx)
        meta = {k: v for k, v in rec.items() if isinstance(v, (str, int, float, bool))}
        meta.update({"source_file": file, "record_position": idx})
        keep_keys = {"LKN", "Bezeichnung", "Interpretation", "Beschreibung"}
        slim = {k: v for k, v in rec.items() if k in keep_keys and v}
        text = flatten_record(slim)
        chunks = chunk_text(text)

        for c_idx, chunk in enumerate(chunks):
            cid = re.sub(r'[^0-9A-Za-z_]+', '_', f"{base}_{rec_id}_{idx}_chunk_{c_idx}")
            all_ids.append(cid)
            all_docs.append(chunk)
            all_meta.append({**meta, "chunk_index": c_idx})

# Duplikate checken
dup = [k for k, v in Counter(all_ids).items() if v > 1]
if dup:
    raise ValueError(f"Doppelte Chunk-IDs gefunden: {dup}")

print(f"Erzeuge Embeddings für {len(all_docs)} Chunks …")

# ── Hinzufügen ────────────────────────────────────────────────────────────────
BATCH_SIZE = 512
for i in tqdm(range(0, len(all_ids), BATCH_SIZE), desc="Chroma-Ingestion"):
    col.add(
        ids=all_ids[i:i+BATCH_SIZE],
        documents=all_docs[i:i+BATCH_SIZE],
        metadatas=all_meta[i:i+BATCH_SIZE]
    )

print("✓ Index erfolgreich erstellt.")
