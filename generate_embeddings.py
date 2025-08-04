"""Generate sentence embeddings for the Leistungskatalog.

This script requires the 'sentence-transformers' package and will output
`data/leistungskatalog_embeddings.json` which maps each LKN code to its
embedding vector.
"""

from pathlib import Path
import json

try:
    from sentence_transformers import SentenceTransformer
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
    raise SystemExit(
        "The 'sentence-transformers' package is required to run this script"
    ) from exc

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DATA_DIR = Path("data")
KATALOG_PATH = DATA_DIR / "LKAAT_Leistungskatalog.json"
OUT_PATH = DATA_DIR / "leistungskatalog_embeddings.json"


def load_katalog() -> list[dict]:
    with KATALOG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    katalog = load_katalog()
    model = SentenceTransformer(MODEL_NAME)
    codes: list[str] = []
    texts: list[str] = []
    for entry in katalog:
        code = entry.get("LKN")
        if not code:
            continue
        parts = []
        for key in ["Beschreibung", "Beschreibung_f", "Beschreibung_i"]:
            val = entry.get(key)
            if val:
                parts.append(str(val))
        if not parts:
            continue
        codes.append(code)
        texts.append(" ".join(parts))

    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)
    payload = {"codes": codes, "embeddings": embeddings.tolist()}
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"Wrote {len(codes)} embeddings to {OUT_PATH}")


if __name__ == "__main__":  # pragma: no cover - manual tool
    main()
