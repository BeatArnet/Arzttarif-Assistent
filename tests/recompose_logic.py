import json
from pathlib import Path
from typing import Dict, List


def recompose_logic(path: Path) -> Dict[str, str]:
    """Return a mapping of pauschalen codes to reconstructed logic strings."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    by_pauschale: Dict[str, List[dict]] = {}
    for row in data:
        code = row.get("Pauschale")
        if code is None:
            continue
        by_pauschale.setdefault(code, []).append(row)

    result: Dict[str, str] = {}
    for code, conds in by_pauschale.items():
        filtered = [c for c in conds if c.get("Bedingungstyp") != "AST VERBINDUNGSOPERATOR"]
        filtered.sort(key=lambda c: c.get("BedingungsID", 0))
        if not filtered:
            result[code] = ""
            continue

        baseline = 1
        first_level = filtered[0].get("Ebene", baseline)
        expr_parts: List[str] = ["(" * (first_level - baseline), str(filtered[0]["BedingungsID"])]
        prev_level = first_level
        prev_op = filtered[0].get("Operator", "UND").upper()

        for cond in filtered[1:]:
            level = cond.get("Ebene", baseline)
            if level < prev_level:
                expr_parts.append(")" * (prev_level - level))
            expr_parts.append(" AND " if prev_op == "UND" else " OR ")
            if level > prev_level:
                expr_parts.append("(" * (level - prev_level))
            expr_parts.append(str(cond["BedingungsID"]))
            prev_level = level
            prev_op = cond.get("Operator", "UND").upper()

        expr_parts.append(")" * (prev_level - baseline))
        result[code] = "".join(expr_parts)

    return result
