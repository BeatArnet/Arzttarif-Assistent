from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import List, Tuple, Callable, Any, cast, TYPE_CHECKING, Dict
import queue
import configparser

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "synonyms"

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Nur für Typprüfer laden – kein Runtime-Import
    import tkinter as tk  # optional, falls du tk.* in Docstrings brauchst
    from tkinter import Event, StringVar
    from tkinter.scrolledtext import ScrolledText as TkScrolledText
else:
    TkScrolledText = Any

try:
    import tkinter as tk
    from tkinter import (
        ttk,
        filedialog,
        messagebox,
        font as tkfont,
    )
    from tkinter.scrolledtext import ScrolledText
except Exception as e:  # pragma: no cover - only needed for GUI
    tk = cast(Any, None)
    ttk = cast(Any, None)
    filedialog = cast(Any, None)
    messagebox = cast(Any, None)
    tkfont = cast(Any, None)
    ScrolledText = cast(Any, None)

from . import generator, storage
from .models import SynonymCatalog, SynonymEntry

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.ini"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class TextHandler(logging.Handler):
    """Logging handler that writes messages to a Tkinter text widget."""
    def __init__(self, widget: TkScrolledText) -> None:
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - GUI
        msg = self.format(record)
        self.widget.configure(state="normal")
        self.widget.insert("end", msg + "\n")
        self.widget.yview("end")
        self.widget.configure(state="disabled")


class GeneratorApp(tk.Tk):  # type: ignore[misc]
    """Simple Tkinter interface for the synonym generator."""

    def __init__(self) -> None:
        if tk is None:
            raise RuntimeError("tkinter not available")
        super().__init__()
        self.title("Synonym Generator")
        self.geometry("800x600")

        self._config = configparser.ConfigParser()
        self._config.read(CONFIG_PATH)
        if self._config.has_option("SYNONYMS", "catalog_path"):
            default_path = Path(self._config.get("SYNONYMS", "catalog_path"))
        else:
            fname = self._config.get("SYNONYMS", "catalog_filename", fallback="synonyms.json")
            default_path = DATA_DIR / fname

        self.output_var = tk.StringVar(value=str(default_path))
        self.start_var = tk.StringVar(value="0")
        self.progress_var = tk.StringVar(value="0/0")
        self.time_per_var = tk.StringVar(value="0 s/req")
        self.eta_var = tk.StringVar(value="ETA")

        top = ttk.Frame(self)
        top.pack(fill="x", pady=5)
        ttk.Label(top, text="Output file:").pack(side="left")
        ttk.Entry(top, textvariable=self.output_var, width=50).pack(
            side="left", expand=True, fill="x"
        )
        ttk.Button(top, text="Browse", command=self._browse_output).pack(side="left")

        frm = ttk.Frame(self)
        frm.pack(fill="x", pady=5)
        ttk.Label(frm, text="Start index:").pack(side="left")
        ttk.Entry(frm, textvariable=self.start_var, width=8).pack(side="left")
        ttk.Button(frm, text="Start", command=self.start).pack(side="left", padx=5)
        ttk.Button(frm, text="Stop", command=self.stop).pack(side="left")

        stat = ttk.Frame(self)
        stat.pack(fill="x", pady=5)
        ttk.Label(stat, textvariable=self.progress_var).pack(side="left", padx=5)
        ttk.Label(stat, textvariable=self.time_per_var).pack(side="left", padx=5)
        ttk.Label(stat, textvariable=self.eta_var).pack(side="left", padx=5)

        self.tree = ttk.Treeview(
            self, columns=("lkn", "term", "syns", "status"), show="headings"
        )
        self.tree.heading("lkn", text="LKN")
        self.tree.heading("term", text="Beschreibung")
        self.tree.heading("syns", text="Synonyme")
        self.tree.heading("status", text="Status")

        # Set column widths based on character counts
        default_font = tkfont.nametofont("TkDefaultFont")
        lkn_width = default_font.measure("0" * 10)
        term_width = default_font.measure("0" * 40)
        syn_width = default_font.measure("0" * 130)
        self.tree.column("lkn", width=lkn_width, minwidth=lkn_width)
        self.tree.column("term", width=term_width, minwidth=term_width)
        self.tree.column("syns", width=syn_width, minwidth=syn_width)

        self.tree.tag_configure("added", background="#d1ffd1")
        self.tree.tag_configure("removed", background="#ffd6d6")
        self.tree.tag_configure("changed", background="#fff2cc")

        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<Double-1>", self._on_double_click)

        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill="x", pady=(0, 5))
        self.only_new_var = tk.BooleanVar(value=False)
        self.only_changed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_frame,
            text="Nur neue",
            variable=self.only_new_var,
            command=self._apply_filter,
        ).pack(side="left", padx=5)
        ttk.Checkbutton(
            filter_frame,
            text="Nur geänderte",
            variable=self.only_changed_var,
            command=self._apply_filter,
        ).pack(side="left")

        # text widget for logging output
        self.log_widget = ScrolledText(self, height=8, state="disabled")
        self.log_widget.pack(fill="both", expand=False, padx=5, pady=(0, 5))

        handler = TextHandler(self.log_widget)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logging.getLogger().addHandler(handler)

        self._queue: "queue.Queue[Tuple[Callable[..., None], Tuple[object, ...]]]" = queue.Queue()
        self.after(100, self._process_queue)

        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._start_index = 0
        self._total = 0
        self._start_time = 0.0
        self._catalog: SynonymCatalog | None = None
        self._orig_catalog: SynonymCatalog | None = None
        self._status_map: dict[str, str] = {}
        self._item_status: dict[str, str] = {}
        self._batch = 0

        output = self.output_var.get()
        if output and Path(output).exists():
            try:
                self._catalog = storage.load_synonyms(output)
                self._orig_catalog = storage.load_synonyms(output)
                self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)
                for base, entry in self._catalog.entries.items():
                    item = self.tree.insert(
                        "", "end",
                        values=(entry.lkn or "", entry.base_term, ", ".join(entry.synonyms), "unchanged"),
                        tags=("unchanged",),
                    )
                    self._item_status[item] = "unchanged"
                self._apply_filter()
                self._update_stats(len(self._item_status))
            except Exception as e:
                logging.exception("Konnte vorhandene Synonyme nicht laden: %s", e)

    def _on_double_click(self, event: Event) -> None:  # pragma: no cover - GUI
        # 1) Katalog bei Bedarf laden (ohne Generator zu starten)
        if self._catalog is None:
            output = self.output_var.get()
            if output and Path(output).exists():
                try:
                    self._catalog = storage.load_synonyms(output)
                    # Falls Tree noch leer ist, optional gleich befüllen:
                    if not self.tree.get_children():
                        for base, entry in self._catalog.entries.items():
                            item = self.tree.insert(
                                "", "end",
                                values=(entry.lkn or "", entry.base_term, ", ".join(entry.synonyms), "unchanged"),
                                tags=("unchanged",),
                            )
                            self._item_status[item] = "unchanged"
                except Exception as e:
                    messagebox.showerror("Fehler", f"Katalog konnte nicht geladen werden:\n{e}")
                    return
            else:
                messagebox.showinfo("Hinweis", "Bitte zuerst einen Katalog laden oder die Generierung starten.")
                return

        # 2) Item zuverlässig ermitteln
        item = self.tree.identify_row(event.y)
        if not item:
            item = self.tree.focus()
        if not item:
            return

        vals = self.tree.item(item, "values")
        if len(vals) < 2:
            return

        base = vals[1]
        entry = self._catalog.entries.get(base)
        if entry is None:
            # Sicherheitsnetz: evtl. Whitespaces/Formatierung
            base_stripped = str(base).strip()
            entry = self._catalog.entries.get(base_stripped)
            if entry is None:
                messagebox.showwarning("Nicht gefunden", f"Eintrag '{base}' nicht im Katalog.")
                return

        self._open_edit_dialog(item, entry)
    def _open_edit_dialog(self, item: str, entry: SynonymEntry) -> None:  # pragma: no cover - GUI
        assert tk is not None
        dialog = tk.Toplevel(self)
        dialog.title(f"Edit synonyms for {entry.base_term}")

        languages = sorted(set(["de", "fr", "it"] + list(entry.by_lang.keys())))
        lang_vars: dict[str, StringVar] = {}
        for i, lang in enumerate(languages):
            ttk.Label(dialog, text=lang.upper() + ":").grid(row=i, column=0, sticky="e", padx=5, pady=2)
            text = ", ".join(entry.by_lang.get(lang, []))
            var = tk.StringVar(value=text)
            lang_vars[lang] = var
            ttk.Entry(dialog, textvariable=var, width=50).grid(row=i, column=1, padx=5, pady=2)

        def save() -> None:
            if self._catalog is None:
                dialog.destroy()
                return
            for lang, var in lang_vars.items():
                items = [s.strip() for s in var.get().split(",") if s.strip()]
                if items:
                    entry.by_lang[lang] = items
                elif lang in entry.by_lang:
                    del entry.by_lang[lang]
            combined: list[str] = []
            for lst in entry.by_lang.values():
                combined.extend(lst)
            # remove duplicates while preserving order
            entry.synonyms = list(dict.fromkeys(combined))
            vals = list(self.tree.item(item, "values"))
            vals[2] = ", ".join(entry.synonyms)
            if self._orig_catalog is not None and self._catalog is not None:
                self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)
                status = self._status_map.get(entry.base_term, vals[3])
                vals[3] = status
                self.tree.item(item, values=vals, tags=(status,))
                self._item_status[item] = status
                self._apply_filter()
            else:
                self.tree.item(item, values=vals)
            output = self.output_var.get()
            if output:
                storage.save_synonyms(self._catalog, output)
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=len(languages), column=0, columnspan=2, pady=5)
        ttk.Button(btn_frame, text="Save", command=save).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=5)

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            self.output_var.set(path)
            self._save_output_filename(path)

    def _save_output_filename(self, path: str) -> None:
        """Persist the selected output file name to config.ini."""
        self._config.read(CONFIG_PATH)
        if "SYNONYMS" not in self._config:
            self._config["SYNONYMS"] = {}
        self._config["SYNONYMS"]["catalog_filename"] = Path(path).name
        with CONFIG_PATH.open("w", encoding="utf-8") as cfg:
            self._config.write(cfg)

    def _process_queue(self) -> None:
        try:
            while True:
                func, args = self._queue.get_nowait()
                func(*args)
        except queue.Empty:
            pass
        self.after(100, self._process_queue)

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
        # auto-detect start index when resuming
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

        self.tree.delete(*self.tree.get_children())
        self._item_status.clear()
        self.progress_var.set(f"0/{self._total}")
        self.time_per_var.set("0 s/req")
        self.eta_var.set("ETA")

        self._catalog = (
            storage.load_synonyms(output)
            if output and Path(output).exists()
            else SynonymCatalog()
        )
        self._orig_catalog = (
            storage.load_synonyms(output)
            if output and Path(output).exists()
            else SynonymCatalog()
        )
        self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)
        self._batch = 0
        self._stop_requested = False
        self._start_time = time.time()

        args = (base_terms, output, self._start_index)
        self._thread = threading.Thread(target=self._run_generator, args=args, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested = True

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

    def _add_row(self, entry: SynonymEntry) -> None:
        if self._orig_catalog is not None and self._catalog is not None:
            self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)
            status = self._status_map.get(entry.base_term, "added")
        else:
            status = "added"
        item = self.tree.insert(
            "",
            "end",
            values=(entry.lkn or "", entry.base_term, ", ".join(entry.synonyms), status),
            tags=(status,),
        )
        self._item_status[item] = status
        self._apply_filter()
        processed = len(self._item_status)
        self._update_stats(processed)

    def _update_stats(self, processed: int) -> None:
        self.progress_var.set(f"{self._start_index + processed}/{self._total}")
        if processed:
            secs = (time.time() - self._start_time) / processed
            self.time_per_var.set(f"{secs:.1f} s/req")
            remaining = self._total - self._start_index - processed
            eta = time.time() + secs * remaining
            self.eta_var.set(time.strftime("ETA %Y-%m-%d %H:%M:%S", time.localtime(eta)))

    def _finish(self) -> None:
        if self._orig_catalog is not None and self._catalog is not None:
            self._status_map = storage.compare_catalogues(self._orig_catalog, self._catalog)
            for item in self.tree.get_children():
                vals = list(self.tree.item(item, "values"))
                base = vals[1]
                status = self._status_map.get(base, vals[3])
                vals[3] = status
                self.tree.item(item, values=vals, tags=(status,))
                self._item_status[item] = status
            for base, status in self._status_map.items():
                if status == "removed":
                    entry = self._orig_catalog.entries[base]
                    item = self.tree.insert(
                        "",
                        "end",
                        values=(entry.lkn or "", base, ", ".join(entry.synonyms), status),
                        tags=(status,),
                    )
                    self._item_status[item] = status
            self._apply_filter()
        self._update_stats(len(self._item_status))
        messagebox.showinfo("Synonym Generator", "Finished")

    def _apply_filter(self) -> None:
        show_new = self.only_new_var.get()
        show_changed = self.only_changed_var.get()
        for item, status in list(self._item_status.items()):
            visible = True
            if show_new or show_changed:
                visible = ((status == "added" and show_new) or (status == "changed" and show_changed))
            if visible:
                self.tree.reattach(item, "", "end")
            else:
                self.tree.detach(item)

def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    app = GeneratorApp()
    app.mainloop()

