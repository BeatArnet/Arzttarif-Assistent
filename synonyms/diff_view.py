from __future__ import annotations

from typing import Dict, List, Tuple, TYPE_CHECKING

from .models import SynonymCatalog, SynonymEntry
from . import storage, generator

try:
    import tkinter as tk  # type: ignore
    from tkinter import ttk, messagebox  # type: ignore
    from . import synonyms_tk
except ModuleNotFoundError:  # pragma: no cover - optional dependency missing
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    synonyms_tk = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover
    from tkinter import Misc

def open_diff_window(
    master: 'Misc', catalog_path: str, leistungskatalog: Dict[str, Dict[str, str]]
) -> None:
    """Open a two-column comparison between synonyms and tariff catalogue."""
    if (
        tk is None
        or ttk is None
        or messagebox is None
        or synonyms_tk is None
    ):
        raise ModuleNotFoundError("tkinter is required for diff_view")
    assert tk is not None
    assert ttk is not None
    assert messagebox is not None
    assert synonyms_tk is not None
    _tk = tk
    _ttk = ttk
    _messagebox = messagebox
    _synonyms_tk = synonyms_tk

    catalog = storage.load_synonyms(catalog_path)

    window = _tk.Toplevel(master)
    window.title("Synonymliste vs. Leistungskatalog")

    tree = _ttk.Treeview(
        window,
        columns=("lkn", "syn", "cat", "status"),
        show="headings",
        selectmode="extended",
    )
    tree.heading("lkn", text="LKN")
    tree.heading("syn", text="Synonym-Liste")
    tree.heading("cat", text="Leistungskatalog")
    tree.heading("status", text="Status")

    tree.column("lkn", width=120, minwidth=80)
    tree.column("syn", width=300, minwidth=200)
    tree.column("cat", width=300, minwidth=200)
    tree.column("status", width=80, minwidth=60)

    tree.tag_configure("added", background="#d1ffd1")
    tree.tag_configure("removed", background="#ffd6d6")
    tree.tag_configure("changed", background="#cce0ff")

    tree.pack(fill="both", expand=True, padx=5, pady=5)

    def rebuild_index() -> None:
        catalog.index.clear()
        for base, entry in catalog.entries.items():
            catalog.index[base.lower()] = base
            for syn in entry.synonyms:
                key = " ".join(syn.lower().split())
                if key:
                    catalog.index.setdefault(key, base)

    def compute_rows() -> List[Tuple[str, str, str, str]]:
        syn_by_lkn: Dict[str, str] = {}
        for base, entry in catalog.entries.items():
            if entry.lkn:
                syn_by_lkn[str(entry.lkn).strip()] = base
        rows: List[Tuple[str, str, str, str]] = []
        all_lkns = set(syn_by_lkn) | set(leistungskatalog)
        for lkn in all_lkns:
            syn_desc = syn_by_lkn.get(lkn, "")
            cat_desc = (
                str(leistungskatalog.get(lkn, {}).get("Beschreibung", ""))
                if lkn in leistungskatalog
                else ""
            )
            if lkn not in syn_by_lkn:
                status = "added"
            elif lkn not in leistungskatalog:
                status = "removed"
            elif syn_desc != cat_desc:
                status = "changed"
            else:
                status = "unchanged"
            rows.append((lkn, syn_desc, cat_desc, status))
        rows.sort(key=lambda r: (r[3] == "unchanged", r[0]))
        return rows

    def refresh() -> None:
        tree.delete(*tree.get_children())
        for row in compute_rows():
            tree.insert("", "end", values=row, tags=(row[3],))

    def selected_rows() -> List[Tuple[str, str, str, str]]:
        return [tuple(tree.item(i, "values")) for i in tree.selection()]  # type: ignore

    def selected_first() -> Tuple[str, str, str, str] | None:
        rows = selected_rows()
        return rows[0] if rows else None

    def delete_selected() -> None:
        sel = selected_first()
        if not sel:
            return
        lkn, syn_desc, _, status = sel
        if status != "removed":
            _messagebox.showinfo(
                "Hinweis", "Nur rot markierte Einträge können gelöscht werden."
            )
            return
        if syn_desc in catalog.entries:
            del catalog.entries[syn_desc]
            rebuild_index()
            storage.save_synonyms(catalog, catalog_path)
        refresh()

    def generate_selected() -> None:
        rows = selected_rows()
        if not rows:
            return
        if any(status != "added" for _, _, _, status in rows):
            _messagebox.showinfo(
                "Hinweis", "Nur grün markierte Einträge können generiert werden."
            )
            return
        terms = [{"de": cat_desc, "lkn": lkn} for lkn, _, cat_desc, _ in rows]
        try:
            entries = list(generator.propose_synonyms_incremental(terms))
        except Exception:
            entries = [
                SynonymEntry(base_term=t["de"], lkn=t.get("lkn"))  # type: ignore[arg-type]
                for t in terms
            ]
        for entry in entries:
            catalog.entries[entry.base_term] = entry
        rebuild_index()
        storage.save_synonyms(catalog, catalog_path)
        refresh()

    def adopt_selected() -> None:
        sel = selected_first()
        if not sel:
            return
        lkn, syn_desc, cat_desc, status = sel
        if status != "changed":
            _messagebox.showinfo(
                "Hinweis", "Nur blau markierte Einträge können angepasst werden."
            )
            return
        entry = catalog.entries.pop(syn_desc, None)
        if entry is None:
            refresh()
            return
        entry.base_term = cat_desc
        catalog.entries[cat_desc] = entry
        rebuild_index()
        storage.save_synonyms(catalog, catalog_path)
        refresh()

    btn_frame = _ttk.Frame(window)
    btn_frame.pack(fill="x", pady=5)
    _ttk.Button(btn_frame, text="Löschen", command=delete_selected).pack(
        side="left", padx=5
    )
    _ttk.Button(btn_frame, text="Generieren", command=generate_selected).pack(
        side="left", padx=5
    )
    _ttk.Button(
        btn_frame,
        text="Beschreibung übernehmen",
        command=adopt_selected,
    ).pack(side="left", padx=5)

    def edit_added(event) -> None:
        sel = selected_first()
        if not sel:
            return
        lkn, _, cat_desc, status = sel
        if status != "added":
            return

        data = {
            lang: {"current": [], "suggestions": []}
            for lang in ("de", "fr", "it")
        }

        def on_save(result: Dict[str, List[str]]) -> None:
            combined = [s for lst in result.values() for s in lst]
            if not combined:
                return # do not save empty entries
            new_entry = SynonymEntry(
                base_term=cat_desc, synonyms=combined, lkn=lkn, by_lang=result
            )
            catalog.entries[cat_desc] = new_entry
            rebuild_index()
            storage.save_synonyms(catalog, catalog_path)
            refresh()

        _synonyms_tk.open_synonym_editor(
            data, on_save, master=window, lkn=lkn, beschreibung_de=cat_desc
        )

    tree.bind("<Double-1>", edit_added)

    refresh()
