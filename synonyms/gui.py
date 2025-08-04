import logging
import threading
import time
from pathlib import Path
from typing import List, Tuple, Callable, Any, cast, TYPE_CHECKING
import queue

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "synonyms"

if TYPE_CHECKING:
    from tkinter.scrolledtext import ScrolledText as TkScrolledText
else:
    TkScrolledText = Any

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, font as tkfont
    from tkinter.scrolledtext import ScrolledText
except Exception as e:  # pragma: no cover - only needed for GUI
    tk = None  # type: ignore
    ttk = cast(Any, None)  # type: ignore
    filedialog = cast(Any, None)  # type: ignore
    messagebox = cast(Any, None)  # type: ignore
    tkfont = cast(Any, None)  # type: ignore
    ScrolledText = cast(Any, None)  # type: ignore

from . import generator, storage
from .models import SynonymCatalog, SynonymEntry


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

        self.output_var = tk.StringVar(value="data/synonyms.json")
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
            self, columns=("lkn", "term", "syns"), show="headings"
        )
        self.tree.heading("lkn", text="LKN")
        self.tree.heading("term", text="Term")
        self.tree.heading("syns", text="Synonyms")

        # Width of the LKN column should match ten characters
        default_font = tkfont.nametofont("TkDefaultFont")
        lkn_width = default_font.measure("0" * 10)
        self.tree.column("lkn", width=lkn_width, minwidth=lkn_width)

        self.tree.pack(fill="both", expand=True, padx=5, pady=5)

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
        self._batch = 0

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            self.output_var.set(path)

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
        self.progress_var.set(f"0/{self._total}")
        self.time_per_var.set("0 s/req")
        self.eta_var.set("ETA")

        self._catalog = (
            storage.load_synonyms(output)
            if output and Path(output).exists()
            else SynonymCatalog()
        )
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
        self.tree.insert(
            "",
            "end",
            values=(entry.lkn or "", entry.base_term, ", ".join(entry.synonyms)),
        )
        processed = len(self.tree.get_children())
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
        self._update_stats(len(self.tree.get_children()))
        messagebox.showinfo("Synonym Generator", "Finished")


def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    app = GeneratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()

