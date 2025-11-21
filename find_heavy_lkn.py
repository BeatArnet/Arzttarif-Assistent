import json
from pathlib import Path
from collections import Counter

DATA_DIR = Path("data")

def analyze_heavy_lkns():
    lp_file = DATA_DIR / "PAUSCHALEN_Leistungspositionen.json"
    bed_file = DATA_DIR / "PAUSCHALEN_Bedingungen.json"

    lkn_counts = Counter()

    print("Analyzing PAUSCHALEN_Leistungspositionen.json...")
    with lp_file.open("r", encoding="utf-8") as f:
        lp_data = json.load(f)
        for item in lp_data:
            lkn = item.get("Leistungsposition")
            if lkn:
                lkn_counts[lkn] += 1

    print("Analyzing PAUSCHALEN_Bedingungen.json...")
    with bed_file.open("r", encoding="utf-8") as f:
        bed_data = json.load(f)
        for item in bed_data:
            typ = item.get("Bedingungstyp", "").upper()
            werte = item.get("Werte", "")
            if typ in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
                lkns = [w.strip() for w in werte.split(",") if w.strip()]
                for lkn in lkns:
                    lkn_counts[lkn] += 1

    print("\nTop 20 Heaviest LKNs (most frequent in definitions):")
    for lkn, count in lkn_counts.most_common(20):
        print(f"{lkn}: {count}")

if __name__ == "__main__":
    analyze_heavy_lkns()
