"""Tkinter-Desktoptool zur Pflege des Synonymkatalogs.

Der Aufruf ``python -m synonyms`` startet eine GUI auf Basis der
Generator- und Speicher-Module. Fachpersonen können damit Katalogeinträge
prüfen, automatische Synonymvorschläge erzeugen, Unterschiede zwischen Versionen
vergleichen und Embeddings exportieren. Diese Datei bündelt vor allem die
UI-Logik: Sie koordiniert Worker-Threads, sichert Einstellungen in ``config.runtime.ini``
und verbindet die im Paket enthaltenen Fenster.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import List, Tuple, Callable, Any, TYPE_CHECKING, Dict, Mapping, cast
import sys
import queue
import configparser
import json
# Paketpfad korrigieren, falls direkt als Skript gestartet
if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "synonyms"

if TYPE_CHECKING:
    from tkinter import Event, StringVar
    from tkinter.scrolledtext import ScrolledText as TkScrolledText
else:
    TkScrolledText = Any  # Laufzeit-Typ ist das echte Widget

# --- Tkinter-Import: NICHT stumm abfangen ---
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, font as tkfont
    from tkinter.scrolledtext import ScrolledText
except ImportError as e:
    raise RuntimeError("tkinter ist nicht installiert oder unter diesem Interpreter nicht verfügbar") from e

from . import generator, storage, synonyms_tk, diff_view
from .models import SynonymCatalog, SynonymEntry
from .synonyms_tk import open_synonym_editor

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.ini"
RUNTIME_CONFIG_PATH = CONFIG_PATH.with_name("config.runtime.json")
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

LEISTUNGSKATALOG_PATH = DATA_DIR / "LKAAT_Leistungskatalog.json"


def load_runtime_config(path: Path = RUNTIME_CONFIG_PATH) -> Dict[str, Dict[str, str]]:
    """Return runtime overrides stored alongside ``config.ini``.

    The GUI stores window geometry and recently used catalogue paths in a
    JSON file so that we do not have to mutate the checked-in ``config.ini``.
    Invalid structures are ignored to keep the application resilient against
    manual edits or truncated files.
    """

    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception:
        logging.exception("Runtime-Konfiguration konnte nicht geladen werden")
        return {}

    if not isinstance(data, dict):
        logging.warning("Runtime-Konfiguration hat unerwartetes Format: %s", type(data).__name__)
        return {}

    result: Dict[str, Dict[str, str]] = {}
    for section, values in data.items():
        if not isinstance(section, str) or not isinstance(values, dict):
            continue
        cleaned: Dict[str, str] = {}
        for key, value in values.items():
            if not isinstance(key, str):
                continue
            cleaned[key] = "" if value is None else str(value)
        if cleaned:
            result[section] = cleaned
    return result


def save_runtime_config(data: Mapping[str, Mapping[str, object]] | Dict[str, Dict[str, object]], path: Path = RUNTIME_CONFIG_PATH) -> None:
    """Persist runtime overrides as JSON with basic validation."""

    serialisable: Dict[str, Dict[str, object]] = {}
    for section, values in data.items():
        if not isinstance(section, str):
            continue
        if not isinstance(values, Mapping):
            continue
        cleaned: Dict[str, object] = {}
        for key, value in values.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        if cleaned:
            serialisable[section] = cleaned

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(serialisable, fh, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        logging.exception("Runtime-Konfiguration konnte nicht gespeichert werden")


def load_merged_config() -> configparser.ConfigParser:
    """Load ``config.ini`` and merge runtime overrides from JSON."""

    config = configparser.ConfigParser()
    try:
        config.read(CONFIG_PATH, encoding="utf-8-sig")
    except Exception:
        logging.exception("CONFIG lesen fehlgeschlagen")

    for section, values in load_runtime_config().items():
        if section not in config:
            config[section] = {}
        config_section = config[section]
        for key, value in values.items():
            config_section[key] = value
    return config
try:
    with LEISTUNGSKATALOG_PATH.open("r", encoding="utf-8") as f:
        _leistungskatalog_list = json.load(f)
    # Katalog mit dem Editor-Dialog teilen, damit Nachschlagen schnell bleibt.
    synonyms_tk.leistungskatalog_dict = {
        str(item.get("LKN")).strip(): item
        for item in _leistungskatalog_list
        if isinstance(item, dict) and item.get("LKN")
    }
except Exception:
    logging.exception("Leistungskatalog konnte nicht geladen werden")


class TextHandler(logging.Handler):
    """Logging-Handler, der in ein Tkinter-Text-Widget schreibt."""
    def __init__(self, widget: TkScrolledText) -> None:
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - GUI
        try:
            # Wenn das Widget bereits zerstört wurde, keine weiteren Logeinträge schreiben
            if not getattr(self.widget, "winfo_exists", lambda: False)():
                return
            msg = self.format(record)
            self.widget.configure(state="normal")
            self.widget.insert("end", msg + "\n")
            self.widget.yview("end")
            self.widget.configure(state="disabled")
        except Exception:
            # Keine erneute Logausgabe, um Rekursion zu vermeiden
            pass


class GeneratorApp(tk.Tk):  # type: ignore[misc]
    """Tkinter-Oberfläche für den Synonym-Generator."""

    def __init__(self) -> None:
        super().__init__()
        logging.debug("Initializing Tkinter window...")
        self.title("Synonym Generator")
        self.resizable(True, True)

        # Tk-Callback-Fehler sichtbar machen
        def _tk_report(exc, val, tb):
            import traceback
            logging.error("Tk callback exception", exc_info=(exc, val, tb))
            try:
                messagebox.showerror("Fehler", "".join(traceback.format_exception(exc, val, tb)))
            except Exception:
                pass
        self.report_callback_exception = _tk_report  # type: ignore[attr-defined]

        # Window-Close-Hook
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Konfiguration und Pfade ---
        self._config = load_merged_config()

        geom = self._config.get("SYNONYMS", "list_geometry", fallback="1200x700")
        try:
            self.geometry(geom)
        except Exception:
            logging.exception("Konnte Fenstergeometrie nicht setzen")

        if self._config.has_option("SYNONYMS", "catalog_path"):
            default_path = Path(self._config.get("SYNONYMS", "catalog_path"))
        else:
            fname = self._config.get("SYNONYMS", "catalog_filename", fallback="synonyms.json")
            default_path = DATA_DIR / fname

        # --- UI-Variablen ---
        self.output_var = tk.StringVar(value=str(default_path))
        self.start_var = tk.StringVar(value="0")
        self.progress_var = tk.StringVar(value="0/0")
        self.time_per_var = tk.StringVar(value="0 s/req")
        self.eta_var = tk.StringVar(value="ETA")

        # --- Top-Leiste ---
        top = ttk.Frame(self)
        top.pack(fill="x", pady=5)
        ttk.Label(top, text="Output file:").pack(side="left")
        ttk.Entry(top, textvariable=self.output_var, width=60).pack(side="left", expand=True, fill="x")
        ttk.Button(top, text="Browse", command=self._browse_output).pack(side="left")

        # --- Steuerleiste ---
        frm = ttk.Frame(self)
        frm.pack(fill="x", pady=5)
        ttk.Label(frm, text="Start index:").pack(side="left")
        ttk.Entry(frm, textvariable=self.start_var, width=8).pack(side="left")
        # "Start" ist redundant zur Aktion "Synonyme generieren" und wird entfernt
        ttk.Button(frm, text="Synonyme generieren", command=self.start).pack(side="left", padx=5)
        ttk.Button(frm, text="Stop", command=self.stop).pack(side="left")
        ttk.Button(frm, text="Embeddings erstellen", command=self._create_embeddings).pack(side="left", padx=5)
        ttk.Button(frm, text="Katalog-Vergleich", command=self._open_diff_view).pack(side="left", padx=5)

        # --- Suche (nach oben verschoben) ---
        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="Suche:").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side="left", expand=True, fill="x")
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        self.search_count_var = tk.StringVar(value="0 Treffer")
        ttk.Label(search_frame, textvariable=self.search_count_var).pack(side="left", padx=5)

        # --- Statuszeile ---
        stat = ttk.Frame(self)
        stat.pack(fill="x", pady=5)
        ttk.Label(stat, textvariable=self.progress_var).pack(side="left", padx=5)
        ttk.Label(stat, textvariable=self.time_per_var).pack(side="left", padx=5)
        ttk.Label(stat, textvariable=self.eta_var).pack(side="left", padx=5)

        # --- Treeview ---
        self.tree = ttk.Treeview(self, columns=("lkn", "term", "syns", "status"), show="headings")
        self.tree.heading("lkn", text="LKN")
        self.tree.heading("term", text="Beschreibung")
        self.tree.heading("syns", text="Synonyme")
        self.tree.heading("status", text="Status")

        default_font = tkfont.nametofont("TkDefaultFont")
        lkn_width = default_font.measure("0" * 15)
        term_width = default_font.measure("0" * 60)
        syn_width = default_font.measure("0" * 200)
        self.tree.column("lkn", width=lkn_width, minwidth=lkn_width)
        self.tree.column("term", width=term_width, minwidth=term_width)
        self.tree.column("syns", width=syn_width, minwidth=syn_width)
        self.tree.column("status", width=default_font.measure(" " * 15))

        if self._config.has_option("SYNONYMS", "list_columns"):
            try:
                widths = [int(w) for w in self._config.get("SYNONYMS", "list_columns").split(",")]
                for col, width in zip(("lkn", "term", "syns", "status"), widths):
                    self.tree.column(col, width=width)
            except Exception:
                logging.exception("Spaltenbreiten konnten nicht geladen werden")

        self.tree.tag_configure("added", background="#d1ffd1")
        self.tree.tag_configure("removed", background="#ffd6d6")
        self.tree.tag_configure("changed", background="#fff2cc")
        self.tree.tag_configure("unchanged", background="")
        self.tree.tag_configure("syn_highlight", foreground="blue")

        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<Double-1>", self._on_double_click)

        # --- Filter ---
        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill="x", pady=(0, 5))
        self.only_new_var = tk.BooleanVar(value=False)
        self.only_changed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="Nur neue", variable=self.only_new_var, command=self._apply_filter).pack(side="left", padx=5)
        ttk.Checkbutton(filter_frame, text="Nur geänderte", variable=self.only_changed_var, command=self._apply_filter).pack(side="left")

        

        # --- Log-Widget ---
        self.log_widget = ScrolledText(self, height=8, state="disabled")
        self.log_widget.pack(fill="both", expand=False, padx=5, pady=(0, 5))

        self._log_handler = TextHandler(self.log_widget)
        self._log_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logging.getLogger().addHandler(self._log_handler)

        # --- Queue / State ---
        self._queue: "queue.Queue[Tuple[Callable[..., None], Tuple[object, ...]]]" = queue.Queue()
        self.after(100, self._process_queue)

        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._start_index = 0
        self._total = 0
        self._start_time = 0.0
        self._catalog: SynonymCatalog | None = None
        self._orig_catalog: SynonymCatalog | None = None
        self._status_map: Dict[str, str] = {}
        self._item_status: Dict[str, str] = {}
        self._batch = 0
        # Embedding-Thread (separat vom Synonym-Thread)
        self._emb_thread: threading.Thread | None = None

        # Index für Doppelklick nach LKN
        self._by_lkn: Dict[str, List[SynonymEntry]] = {}
        # Zuordnung Treeview-Item -> LKN für Teilgenerierung
        self._item_by_lkn: Dict[str, List[str]] = {}
        self._terms_by_lkn: Dict[str, dict] = {}
        self._item_by_base: Dict[str, str] = {}
        # Basisbegriffe nach LKN für Teilgenerierung

        # --- WICHTIG: Vorhandene Datei beim Start laden und anzeigen ---
        output_path = Path(self.output_var.get())
        if output_path.exists():
            logging.debug("Lade bestehenden Katalog aus %s", output_path)
            self._load_catalog_to_tree(output_path)
        else:
            logging.debug("Kein bestehender Katalog gefunden unter %s", output_path)

    # ---------- Window-Close ----------
    def on_closing(self) -> None:
        self._save_window_state()
        logger = logging.getLogger()
        if getattr(self, "_log_handler", None):
            try:
                logger.removeHandler(self._log_handler)
                self._log_handler.close()
            except Exception:
                pass
        self._stop_requested = True
        if self._thread is not None and self._thread.is_alive():
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                logging.exception("Fehler beim Warten auf Worker-Thread")
        try:
            self.destroy()  # beendet mainloop sauber
        except Exception:
            pass

    def _save_window_state(self) -> None:
        try:
            if "SYNONYMS" not in self._config:
                self._config["SYNONYMS"] = {}
            section = self._config["SYNONYMS"]
            section["list_geometry"] = self.geometry()
            widths = [str(self.tree.column(col, "width")) for col in ("lkn", "term", "syns", "status")]
            section["list_columns"] = ",".join(widths)

            runtime = load_runtime_config()
            runtime_section = runtime.setdefault("SYNONYMS", {})
            runtime_section["list_geometry"] = section["list_geometry"]
            runtime_section["list_columns"] = section["list_columns"]
            save_runtime_config(runtime)
        except Exception:
            logging.exception("Fensterzustand konnte nicht gespeichert werden")

    # ---------- Katalog laden & Tree füllen ----------
    def _load_catalog_to_tree(self, path: Path) -> None:
        """Lädt einen existierenden Katalog und füllt den Treeview."""
        try:
            catalog = storage.load_synonyms(str(path))
        except Exception as e:
            logging.exception("Katalog konnte nicht geladen werden")
            messagebox.showerror("Fehler", f"Katalog konnte nicht geladen werden:\n{e}")
            return

        # interner Status vorbereiten
        self._catalog = catalog
        # Original zum Vergleichen (Änderungsstatus)
        try:
            self._orig_catalog = storage.load_synonyms(str(path))
        except Exception:
            self._orig_catalog = SynonymCatalog()

        self.tree.delete(*self.tree.get_children())
        self._item_status.clear()
        self._by_lkn.clear()

        # Einträge sortiert anzeigen (erst LKN, dann Term)
        def sort_key(e: SynonymEntry):
            first_lkn = e.lkns[0] if e.lkns else ""
            return (first_lkn, e.base_term)

        count = 0
        for entry in sorted(catalog.entries.values(), key=sort_key):
            item = self.tree.insert(
                "", "end",
                values=(", ".join(entry.lkns), entry.base_term, ", ".join(entry.synonyms), "unchanged"),
                tags=("unchanged",),
            )
            self._item_status[item] = "unchanged"
            self._item_by_base[entry.base_term] = item
            count += 1

        self._rebuild_lkn_lookup()

        self._total = count or 0
        self._start_index = 0
        self.progress_var.set(f"{count}/{count}")
        self.time_per_var.set("0 s/req")
        self.eta_var.set("ETA")
        self._apply_filter()
        self._rebuild_lkn_lookup()
        logging.info("Katalog geladen: %d Eintraege", count)

    def _rebuild_lkn_lookup(self) -> None:
        """Synchronise reverse indexes for LKN and base-term lookups."""
        self._by_lkn.clear()
        self._item_by_lkn.clear()
        self._item_by_base.clear()
        if self._catalog is None:
            return
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            if len(values) < 2:
                continue
            base_term = str(values[1]).strip()
            if not base_term:
                continue
            entry = self._catalog.entries.get(base_term)
            if not entry:
                continue
            self._item_by_base[base_term] = item_id
            for code in entry.lkns:
                code_norm = str(code).strip().upper()
                if not code_norm:
                    continue
                self._by_lkn.setdefault(code_norm, []).append(entry)
                self._item_by_lkn.setdefault(code_norm, []).append(item_id)


    # ---------- GUI Events ----------
    def _on_double_click(self, event: "Event") -> None:  # pragma: no cover - GUI
        if self._catalog is None:
            output = self.output_var.get()
            if output and Path(output).exists():
                try:
                    self._catalog = storage.load_synonyms(output)
                except Exception as e:
                    messagebox.showerror("Fehler", f"Katalog konnte nicht geladen werden:\n{e}")
                    return
            else:
                messagebox.showinfo("Hinweis", "Bitte zuerst einen Katalog laden oder die Generierung starten.")
                return

        item = self.tree.identify_row(event.y) or self.tree.focus()
        if not item:
            return
        col = self.tree.identify_column(event.x)  # '#1'=LKN, '#2'=Term, '#3'=Syns, '#4'=Status
        vals = self.tree.item(item, "values")
        if len(vals) < 2:
            return

        entry: SynonymEntry | None = None
        if col == "#1":
            raw_codes = str(vals[0]).split(",")
            for code in raw_codes:
                code_norm = code.strip().upper()
                if not code_norm:
                    continue
                entries = self._by_lkn.get(code_norm)
                if entries:
                    entry = entries[0]
                    break
        if entry is None:
            base = str(vals[1]).strip()
            entry = self._catalog.entries.get(base)

        if entry is None:
            messagebox.showwarning("Nicht gefunden", "Eintrag konnte nicht ermittelt werden.")
            return

        # Prepare data structure for the new synonym editor
        languages = sorted(set(["de", "fr", "it"] + list(entry.by_lang.keys())))
        editor_data: Dict[str, Dict[str, List[str]]] = {
            lang: {"current": entry.by_lang.get(lang, []), "suggestions": []}
            for lang in languages
        }

        def on_save(result: Dict[str, List[str]], new_lkns: List[str]) -> None:
            if self._catalog is None:
                return
            entry.by_lang.clear()
            for lang, syns in result.items():
                if syns:
                    entry.by_lang[lang] = list(dict.fromkeys(syns))
            combined: List[str] = []
            for lst in entry.by_lang.values():
                combined.extend(lst)
            entry.synonyms = list(dict.fromkeys(combined))

            normalized_lkns: List[str] = []
            for code in new_lkns:
                code_norm = str(code).strip().upper()
                if code_norm and code_norm not in normalized_lkns:
                    normalized_lkns.append(code_norm)
            entry.lkns = normalized_lkns

            vals = list(self.tree.item(item, "values"))
            if vals:
                vals[0] = ", ".join(entry.lkns)
            else:
                vals = [", ".join(entry.lkns), entry.base_term, ", ".join(entry.synonyms)]

            if len(vals) >= 3:
                vals[2] = ", ".join(entry.synonyms)
            else:
                while len(vals) < 3:
                    vals.append("")
                vals[2] = ", ".join(entry.synonyms)

            storage.rebuild_indexes(self._catalog)
            self._rebuild_lkn_lookup()

            if self._orig_catalog is not None:
                self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)
                status = self._status_map.get(entry.base_term, vals[3] if len(vals) > 3 else "changed")
                if len(vals) > 3:
                    vals[3] = status
                else:
                    vals.append(status)
                self.tree.item(item, values=vals, tags=(status,))
                self._item_status[item] = status
                self._apply_filter()
            else:
                self.tree.item(item, values=vals)

            output = self.output_var.get()
            if output:
                storage.save_synonyms(self._catalog, output)

        open_synonym_editor(
            cast(
                Dict[str, Dict[str, List[str]] | Dict[str, List[Dict[str, str]]]],
                editor_data,
            ),
            on_save=on_save,
            master=self,
            lkns=list(entry.lkns),
            beschreibung_de=entry.base_term,
        )

    # ---------- Datei wählen / speichern ----------
    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            self.output_var.set(path)
            self._save_output_filename(path)
            p = Path(path)
            if p.exists():
                self._load_catalog_to_tree(p)
            else:
                # neue Datei – UI zurücksetzen
                self.tree.delete(*self.tree.get_children())
                self._item_status.clear()
                self._by_lkn.clear()
                self.progress_var.set("0/0")
                self.time_per_var.set("0 s/req")
                self.eta_var.set("ETA")
                self._catalog = SynonymCatalog()
                self._orig_catalog = SynonymCatalog()

    def _save_output_filename(self, path: str) -> None:
        try:
            if "SYNONYMS" not in self._config:
                self._config["SYNONYMS"] = {}
            section = self._config["SYNONYMS"]
            selected_path = Path(path)
            filename = selected_path.name
            section["catalog_filename"] = filename
            section["catalog_path"] = str(selected_path)

            runtime = load_runtime_config()
            runtime_section = runtime.setdefault("SYNONYMS", {})
            runtime_section["catalog_filename"] = filename
            runtime_section["catalog_path"] = str(selected_path)
            save_runtime_config(runtime)
        except Exception:
            logging.exception("Konnte runtime-Konfiguration nicht schreiben")

    # ---------- Queue / Timer ----------
    def _process_queue(self) -> None:
        try:
            while True:
                func, args = self._queue.get_nowait()
                try:
                    func(*args)
                except Exception:
                    logging.exception("Fehler im GUI-Callback aus der Queue")
                    try:
                        messagebox.showerror("Fehler", "Ein GUI-Callback ist abgestürzt. Details im Log.")
                    except Exception:
                        pass
        except queue.Empty:
            pass
        self.after(100, self._process_queue)

    def _open_diff_view(self) -> None:
        """Open two-column comparison between synonyms and tariff catalogue."""
        output = self.output_var.get()
        if not output:
            messagebox.showinfo("Hinweis", "Bitte zuerst einen Katalogpfad wählen.")
            return
        try:
            diff_view.open_diff_window(self, output, synonyms_tk.leistungskatalog_dict or {})
        except Exception as e:  # pragma: no cover - GUI
            messagebox.showerror("Fehler", f"Ansicht konnte nicht geöffnet werden:\n{e}")

    def _load_terms(self) -> None:
        """Load base terms and existing catalog into the table."""
        output = self.output_var.get()
        self._catalog = (
            storage.load_synonyms(output)
            if output and Path(output).exists()
            else SynonymCatalog()
        )
        self.tree.delete(*self.tree.get_children())
        self._item_by_lkn.clear()
        self._item_by_base.clear()
        self._terms_by_lkn.clear()
        base_terms = generator.extract_base_terms_from_tariff()
        for item in base_terms:
            lkn = str(item.get("lkn") or "")
            term = item.get("de", "")
            if lkn:
                code_norm = lkn.strip().upper()
                if code_norm:
                    self._terms_by_lkn[code_norm] = item
            cat_entry = self._catalog.entries.get(term)
            syns = ", ".join(cat_entry.synonyms) if cat_entry else ""
            iid = self.tree.insert("", "end", values=(lkn, term, syns))
            if lkn:
                code_norm = lkn.strip().upper()
                if code_norm:
                    self._item_by_lkn.setdefault(code_norm, []).append(iid)

    def generate_selected(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Synonym Generator", "Keine Einträge ausgewählt")
            return
        base_terms: List[dict] = []
        for iid in selected:
            lkn_value, term, _ = self.tree.item(iid, "values")
            codes = [code.strip().upper() for code in str(lkn_value).split(",") if code.strip()]
            appended = False
            for code in codes:
                if code in self._terms_by_lkn:
                    base_terms.append(self._terms_by_lkn[code])
                    appended = True
                    break
            if not appended:
                payload = {"de": term}
                if codes:
                    payload["lkn"] = codes[0]
                    payload["lkns"] = codes
                base_terms.append(payload)
        output = self.output_var.get()
        if self._catalog is None:
            self._catalog = (
                storage.load_synonyms(output)
                if output and Path(output).exists()
                else SynonymCatalog()
            )
        self._total = len(base_terms)
        self._start_index = 0
        self._start_time = time.time()
        self.progress_var.set(f"0/{self._total}")
        self.time_per_var.set("0 s/req")
        self.eta_var.set("ETA")
        args = (base_terms, output)
        self._thread = threading.Thread(target=self._run_selected, args=args, daemon=True)
        self._thread.start()
    # ---------- Start/Stop ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        try:
            self._start_index = int(self.start_var.get() or 0)
        except ValueError:
            messagebox.showerror("Error", "Invalid start index")
            return

        output = self.output_var.get()
        if output:
            self._save_output_filename(output)

        if self._start_index == 0 and output and Path(output).exists():
            cat = storage.load_synonyms(output)
            self._start_index = len(cat.entries)
            self.start_var.set(str(self._start_index))

        entries = generator.extract_base_terms_from_tariff()
        base_terms = entries
        self._total = len(base_terms)
        if self._start_index >= self._total:
            messagebox.showinfo("Info", "Start index beyond available terms")
            return

        # UI reset für neuen Lauf
        self.tree.delete(*self.tree.get_children())
        self._item_status.clear()
        self._by_lkn.clear()
        self.progress_var.set(f"0/{self._total}")
        self.time_per_var.set("0 s/req")
        self.eta_var.set("ETA")

        self._catalog = (storage.load_synonyms(output) if output and Path(output).exists() else SynonymCatalog())
        self._orig_catalog = (storage.load_synonyms(output) if output and Path(output).exists() else SynonymCatalog())
        self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)

        self._batch = 0
        self._stop_requested = False
        self._start_time = time.time()

        args = (base_terms, output or "", self._start_index)
        self._thread = threading.Thread(target=self._run_generator, args=args, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested = True

    # ---------- Worker ----------
    def _run_generator(self, base_terms: List[dict], output: str, start: int) -> None:
        assert self._catalog is not None
        catalog = self._catalog
        for entry in generator.propose_synonyms_incremental(base_terms, start=start):
            if self._stop_requested:
                break
            catalog.entries[entry.base_term] = entry
            self._queue.put((self._add_row, (entry,)))
            self._batch += 1
            if output and self._batch >= 50:
                storage.save_synonyms(catalog, output)
                self._batch = 0
        if output:
            storage.save_synonyms(catalog, output)
        self._queue.put((self._finish, ()))

    def _run_selected(self, base_terms: List[dict], output: str) -> None:
        assert self._catalog is not None
        catalog = self._catalog
        processed = 0
        for entry in generator.propose_synonyms_incremental(base_terms):
            catalog.entries[entry.base_term] = entry
            self._queue.put((self._update_row, (entry,)))
            processed += 1
            self._queue.put((self._update_stats, (processed,)))
        if output:
            storage.save_synonyms(catalog, output)
        self._queue.put((self._finish_selection, ()))
    # ---------- GUI-Updates aus Queue ----------
    def _add_row(self, entry: SynonymEntry) -> None:
        codes_display = ", ".join(entry.lkns)
        iid = self.tree.insert(
            "",
            "end",
            values=(codes_display, entry.base_term, ", ".join(entry.synonyms)),
        )
        self._item_by_base[entry.base_term] = iid
        if self._catalog is not None:
            storage.rebuild_indexes(self._catalog)
        self._rebuild_lkn_lookup()
        processed = len(self.tree.get_children())
        self._update_stats(processed)

    def _update_row(self, entry: SynonymEntry) -> None:
        codes_display = ", ".join(entry.lkns)
        values = (codes_display, entry.base_term, ", ".join(entry.synonyms))
        iid = self._item_by_base.get(entry.base_term)
        if iid:
            self.tree.item(iid, values=values)
        else:
            iid = self.tree.insert("", "end", values=values)
            self._item_by_base[entry.base_term] = iid
        if self._catalog is not None:
            storage.rebuild_indexes(self._catalog)
        self._rebuild_lkn_lookup()

    def _update_stats(self, processed: int) -> None:
        self.progress_var.set(f"{self._start_index + processed}/{self._total}")
        if processed:
            secs = (time.time() - self._start_time) / max(processed, 1)
            self.time_per_var.set(f"{secs:.1f} s/req")
            remaining = max(self._total - self._start_index - processed, 0)
            eta = time.time() + secs * remaining
            self.eta_var.set(time.strftime("ETA %Y-%m-%d %H:%M:%S", time.localtime(eta)))

    def _finish(self) -> None:
        if self._orig_catalog is not None and self._catalog is not None:
            self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)
            for item in self.tree.get_children():
                vals = list(self.tree.item(item, "values"))
                base = vals[1]
                status = self._status_map.get(base, vals[3] if len(vals) > 3 else "unchanged")
                if len(vals) > 3:
                    vals[3] = status
                else:
                    vals.append(status)
                self.tree.item(item, values=vals, tags=(status,))
                self._item_status[item] = status
            for base, status in self._status_map.items():
                if status == "removed":
                    entry = self._orig_catalog.entries[base]
                    item = self.tree.insert(
                        "", "end",
                        values=(", ".join(entry.lkns), base, ", ".join(entry.synonyms), status),
                        tags=(status,),
                    )
                    self._item_status[item] = status
            self._rebuild_lkn_lookup()
            self._apply_filter()
        self._update_stats(len(self._item_status))
        try:
            messagebox.showinfo("Synonym Generator", "Finished")
        except Exception:
            pass

    def _finish_selection(self) -> None:
        """Final GUI update after generating a selection."""
        # progress might already be up to date, but ensure final display
        self._update_stats(self._total)
        try:
            messagebox.showinfo("Synonym Generator", "Finished")
        except Exception:
            pass

    def _apply_filter(self) -> None:
        show_new = self.only_new_var.get()
        show_changed = self.only_changed_var.get()
        search = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        count = 0
        for item, status in list(self._item_status.items()):
            values = self.tree.item(item, "values")
            lkn, term, syns = values[0], values[1], values[2]
            matches_search = True
            syn_match = False
            if search:
                lkn_val = str(lkn).lower()
                term_val = str(term).lower()
                syn_val = str(syns).lower()
                matches_search = (
                    search in lkn_val or search in term_val or search in syn_val
                )
                syn_match = search in syn_val
            visible = matches_search
            if show_new or show_changed:
                visible = visible and (
                    (status == "added" and show_new)
                    or (status == "changed" and show_changed)
                )
            if visible:
                self.tree.reattach(item, "", "end")
                tags = [status]
                if syn_match:
                    tags.append("syn_highlight")
                self.tree.item(item, tags=tags)
                count += 1
            else:
                self.tree.detach(item)
        if hasattr(self, "search_count_var"):
            self.search_count_var.set(f"{count} Treffer")

    # ---------- Embeddings ----------
    def _create_embeddings(self) -> None:
        if self._emb_thread and self._emb_thread.is_alive():
            return
        # Starte das bestehende Tool generate_embeddings.py in einem Thread
        self._emb_thread = threading.Thread(target=self._run_embeddings_script, daemon=True)
        self._emb_thread.start()

    def _run_embeddings_script(self) -> None:
        class _QueueWriter:
            def __init__(self, put_line: Callable[[str], None]) -> None:
                self._buf = ""
                self._put = put_line

            def write(self, s: str) -> int:  # type: ignore[override]
                if not isinstance(s, str):
                    s = str(s)
                # tqdm nutzt \r für Fortschritts-Updates; in neue Zeilen verwandeln
                s = s.replace("\r", "\n")
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    if line:
                        self._put(line)
                return len(s)

            def flush(self) -> None:  # type: ignore[override]
                if self._buf:
                    self._put(self._buf)
                    self._buf = ""

        def _put_to_log(line: str) -> None:
            self._queue.put((self._append_log, (line,)))

        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = _QueueWriter(_put_to_log)  # type: ignore[assignment]
        sys.stderr = _QueueWriter(_put_to_log)  # type: ignore[assignment]
        try:
            import generate_embeddings as ge
            logging.info("Embeddings: starte Generierung über generate_embeddings.main() ...")
            ge.main()
            out_path = str(DATA_DIR / "leistungskatalog_embeddings.json")
            self._queue.put((self._finish_embeddings, (out_path,)))
        except SystemExit as e:
            msg = str(e) or "Abgebrochen"
            self._queue.put((self._show_error, ("Embeddings", msg)))
        except Exception as e:
            self._queue.put((self._show_error, ("Embeddings", f"Fehlgeschlagen: {e}",)))
        finally:
            try:
                sys.stdout = old_out  # type: ignore[assignment]
                sys.stderr = old_err  # type: ignore[assignment]
            except Exception:
                pass

    def _finish_embeddings(self, out_path: str) -> None:
        try:
            messagebox.showinfo("Embeddings", f"Embeddings erstellt: {out_path}")
        except Exception:
            pass

    def _show_error(self, title: str, msg: str) -> None:
        try:
            messagebox.showerror(title, msg)
        except Exception:
            pass

    def _append_log(self, line: str) -> None:  # pragma: no cover - GUI
        try:
            self.log_widget.configure(state="normal")
            self.log_widget.insert("end", line + "\n")
            self.log_widget.yview("end")
            self.log_widget.configure(state="disabled")
        except Exception:
            pass

def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    logging.debug("Starte GUI...")
    app = GeneratorApp()
    logging.debug("GUI erstellt – starte mainloop")
    app.mainloop()
    logging.debug("mainloop beendet")

if __name__ == "__main__":
    main()




