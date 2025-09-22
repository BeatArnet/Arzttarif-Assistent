import json
import os
import sys
import time
import importlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - optional GUI
    tk = None
    ttk = None

from utils import count_tokens

# Logdatei des Servers für Tokenabrechnung
LOG_PATH = Path(__file__).with_name("_server.log")


def _read_new_tokens(log_file) -> tuple[int, int]:
    """Liest neue Logzeilen und extrahiert Prompt-/Antworttokenzahlen."""
    in_tokens = 0
    out_tokens = 0
    for line in log_file.read().splitlines():
        if "Prompt Tokens:" in line:
            try:
                in_tokens += int(line.rsplit(":", 1)[1].strip())
            except ValueError:
                continue
        elif "Antwort Tokens:" in line:
            try:
                out_tokens += int(line.rsplit(":", 1)[1].strip())
            except ValueError:
                continue
    return in_tokens, out_tokens

# Ablage der Vergleichsergebnisse im Projektstamm
MODELS_FILE = Path(__file__).with_name("llm_vergleich_results.json")
BASELINE_PATH = Path(__file__).resolve().parent / "data" / "baseline_results.json"


def load_models() -> List[Dict[str, Any]]:
    with MODELS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_models(models: List[Dict[str, Any]]) -> None:
    with MODELS_FILE.open("w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=4)


def load_server(
    stage1_provider: str,
    stage1_model: str,
    stage2_provider: str | None = None,
    stage2_model: str | None = None,
):
    """(Re)load the server module with stage-specific LLM settings."""

    os.environ["STAGE1_LLM_PROVIDER"] = stage1_provider
    os.environ["STAGE1_LLM_MODEL"] = stage1_model
    os.environ["STAGE2_LLM_PROVIDER"] = stage2_provider or stage1_provider
    os.environ["STAGE2_LLM_MODEL"] = stage2_model or stage1_model

    if "server" in sys.modules:
        return importlib.reload(sys.modules["server"])
    import server  # noqa: F401  # first import
    return server


class QCStatus:
    """Einfache Tkinter-Statusanzeige für den LLM-Vergleich."""

    def __init__(self) -> None:
        self.root: Any | None = None
        if tk is None:
            return
        try:  # pragma: no cover - GUI only
            self.root = tk.Tk()
        except Exception:
            self.root = None
            return
        self.root.title("LLM Vergleich")
        self.model_var = tk.StringVar()
        self.progress_var = tk.StringVar()
        tk.Label(self.root, textvariable=self.model_var).pack()
        tk.Label(self.root, textvariable=self.progress_var).pack()
        self.root.update()

    def set_model(self, name: str) -> None:
        if self.root:
            self.model_var.set(name)
            self.root.update()

    def update(self, current: int, total: int) -> None:
        if self.root:
            self.progress_var.set(f"{current}/{total} tests")
            self.root.update()

    def close(self) -> None:
        if self.root:
            self.root.destroy()

    def show_summary(self, models: List[Dict[str, Any]]) -> None:
        """Zeigt nach Abschluss eine Tabelle mit den wichtigsten Kennzahlen.

        Spalten:
        - Modell
        - Zeitbedarf (MM:SS)
        - Korrekt beantwortet
        - n Input Token
        - n Output Token
        - Geschätzte Kosten [CHF]
        """
        if not self.root or tk is None or ttk is None:
            # Fallback: Textuelle Ausgabe in Konsole
            print("\nLLM-Vergleich – Zusammenfassung:")
            for m in models:
                provider = str(m.get("Provider") or m.get("Stage1Provider") or "?")
                model = str(m.get("Model") or m.get("Stage1Model") or "?")
                name = f"{provider}/{model}".strip("/")
                secs = float(m.get("Runtime_Seconds") or 0.0)
                mm = int(secs // 60)
                ss = int(secs % 60)
                passed = int(m.get("Passed") or 0)
                total = int(m.get("Total_Tests") or 0)
                pct = float(m.get("Prozent_Korrekt") or 0.0)
                input_t = int(m.get("InputTokens") or 0)
                output_t = int(m.get("OutputTokens") or 0)
                cost = float(m.get("InputToken_CHF") or 0.0) + float(m.get("OutputToken_CHF") or 0.0)
                print(f"- {name:28}  {mm:02d}:{ss:02d}  {passed}/{total} ({pct:.2f}%)  in:{input_t}  out:{output_t}  CHF {cost:.6f}")
            try:
                input("\n[Enter] zum Beenden … ")
            except Exception:
                pass
            return

        # GUI: bestehende Widgets ersetzen
        for child in list(self.root.children.values()):
            try:
                child.destroy()
            except Exception:
                pass
        self.root.title("LLM Vergleich – Zusammenfassung")
        cols = ("Modell", "Zeit", "Korrekt", "Input Tokens", "Output Tokens", "Kosten [CHF]")
        tree = ttk.Treeview(self.root, columns=cols, show="headings", height=max(6, len(models)))
        for c in cols:
            tree.heading(c, text=c)
        tree.column("Modell", width=320, anchor="w")
        tree.column("Zeit", width=80, anchor="center")
        tree.column("Korrekt", width=140, anchor="center")
        tree.column("Input Tokens", width=120, anchor="e")
        tree.column("Output Tokens", width=120, anchor="e")
        tree.column("Kosten [CHF]", width=120, anchor="e")

        # Einträge füllen
        for m in models:
            provider = str(m.get("Provider") or m.get("Stage1Provider") or "?")
            model = str(m.get("Model") or m.get("Stage1Model") or "?")
            name = f"{provider}/{model}".strip("/")
            secs = float(m.get("Runtime_Seconds") or 0.0)
            mm = int(secs // 60)
            ss = int(secs % 60)
            passed = int(m.get("Passed") or 0)
            total = int(m.get("Total_Tests") or 0)
            pct = float(m.get("Prozent_Korrekt") or 0.0)
            input_t = int(m.get("InputTokens") or 0)
            output_t = int(m.get("OutputTokens") or 0)
            cost = float(m.get("InputToken_CHF") or 0.0) + float(m.get("OutputToken_CHF") or 0.0)
            tree.insert(
                "",
                "end",
                values=(
                    name,
                    f"{mm:02d}:{ss:02d}",
                    f"{passed}/{total} ({pct:.2f}%)",
                    f"{input_t}",
                    f"{output_t}",
                    f"{cost:.6f}",
                ),
            )
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        btn = tk.Button(self.root, text="Ende", command=self.root.destroy)
        btn.pack(pady=(0, 8))
        # GUI offen halten, bis Benutzer schließt
        self.root.update()
        self.root.mainloop()


def _build_examples(baseline: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    examples: List[Tuple[str, str, str]] = []
    for ex_id in sorted(baseline, key=lambda x: int(x)):
        ex_entry = baseline[ex_id]
        for lang in sorted(ex_entry.get("query", {})):
            query = ex_entry["query"][lang]
            examples.append((ex_id, lang, query))
    return examples


def run_qc(entry: Dict[str, Any], models: List[Dict[str, Any]], status: QCStatus) -> None:
    s1_provider: str = str(entry.get("Stage1Provider") or entry.get("Provider") or "")
    s1_model: str = str(entry.get("Stage1Model") or entry.get("Model") or "")
    s2_provider: str = str(entry.get("Stage2Provider") or entry.get("Provider") or "")
    s2_model: str = str(entry.get("Stage2Model") or entry.get("Model") or "")
    srv = load_server(s1_provider, s1_model, s2_provider, s2_model)
    app = srv.app

    with BASELINE_PATH.open("r", encoding="utf-8") as f:
        baseline_data = json.load(f)

    examples = _build_examples(baseline_data)
    total_examples = len(examples)

    # Immer frischen Lauf starten: Vorhandene Resultate überschreiben
    progress_index = 0
    passed = 0
    input_tokens = 0
    output_tokens = 0
    remarks: List[Dict[str, Any]] = []
    runtime_seconds = 0.0

    # Direkt persistieren, damit ein Neustart saubere Werte zeigt
    entry.update(
        {
            "Total_Tests": total_examples,
            "Progress_Index": progress_index,
            "Passed": passed,
            "InputTokens": input_tokens,
            "OutputTokens": output_tokens,
            "Bemerkungen": remarks,
            "Runtime_Seconds": runtime_seconds,
        }
    )
    # Zusammenfassungen werden am Ende neu berechnet; hier optional auf 0 setzen
    entry["Prozent_Korrekt"] = 0.0
    entry["InputToken_CHF"] = 0.0
    entry["OutputToken_CHF"] = 0.0
    entry["Zeit_Stunden"] = 0.0
    save_models(models)

    status.set_model(f"S1:{s1_provider}/{s1_model} | S2:{s2_provider}/{s2_model}")
    start_time = time.time()

    # Token-Erfassung aus Logdatei, falls vorhanden
    try:
        log_file = LOG_PATH.open("r", encoding="utf-8")
        log_file.seek(0, os.SEEK_END)
    except OSError:
        log_file = None

    with app.test_client() as client:
        for idx in range(progress_index, total_examples):
            ex_id, lang, query = examples[idx]

            resp = client.post("/api/test-example", json={"id": int(ex_id), "lang": lang})
            if resp.status_code != 200:
                remarks.append({"id": ex_id, "lang": lang, "error": f"HTTP {resp.status_code}"})
            else:
                data = resp.get_json() or {}

                # Tokenzählung: bevorzugt vom Server gemeldete token_usage; sonst Logdatei; sonst Heuristik
                counted = False
                tu = data.get("token_usage") or {}
                try:
                    if isinstance(tu, dict):
                        in_sum = 0
                        out_sum = 0
                        for stage in (tu.get("llm_stage1"), tu.get("llm_stage2")):
                            if isinstance(stage, dict):
                                in_sum += int(stage.get("input_tokens") or 0)
                                out_sum += int(stage.get("output_tokens") or 0)
                        if (in_sum + out_sum) > 0:
                            input_tokens += in_sum
                            output_tokens += out_sum
                            counted = True
                except Exception:
                    counted = False

                if not counted and log_file is not None:
                    new_in, new_out = _read_new_tokens(log_file)
                    input_tokens += new_in
                    output_tokens += new_out
                    counted = True

                if not counted:
                    # Fallback: einfache Schätzung über Query- und Result-Text
                    input_tokens += count_tokens(query)
                    result_text = json.dumps(data.get("result", {}), ensure_ascii=False)
                    output_tokens += count_tokens(result_text)

                if data.get("passed"):
                    passed += 1
                else:
                    diff = data.get("diff", "")
                    remarks.append({"id": ex_id, "lang": lang, "error": diff})

            progress_index = idx + 1
            runtime_seconds += time.time() - start_time
            start_time = time.time()
            entry.update(
                {
                    "Progress_Index": progress_index,
                    "Passed": passed,
                    "InputTokens": input_tokens,
                    "OutputTokens": output_tokens,
                    "Bemerkungen": remarks,
                    "Runtime_Seconds": runtime_seconds,
                }
            )
            save_models(models)
            status.update(progress_index, total_examples)

    if log_file is not None:
        log_file.close()

    if progress_index >= total_examples:
        entry["Prozent_Korrekt"] = round((passed / total_examples * 100) if total_examples else 0.0, 2)
        entry["InputToken_CHF"] = round(entry["Price_Input_CHF"] * (input_tokens / 1_000_000), 6)
        entry["OutputToken_CHF"] = round(entry["Price_Output_CHF"] * (output_tokens / 1_000_000), 6)
        entry["Zeit_Stunden"] = round(runtime_seconds / 3600, 4)
        save_models(models)


def main() -> None:
    models = load_models()
    status = QCStatus()
    try:
        for entry in models:
            run_qc(entry, models, status)
        # Nach Abschluss: Zusammenfassung anzeigen und auf Ende warten
        status.show_summary(models)
    finally:
        try:
            status.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
