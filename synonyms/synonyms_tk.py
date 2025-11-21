"""Tkinter-based synonym editor – multi-section (DE/FR/IT) layout per mockup.

The editor is opened per LKN to manage multilingual synonym sets. Use
``open_synonym_editor`` to display the dialog within the existing application
window. FR/IT descriptions are taken from global ``leistungskatalog_dict`` if present.
"""

from __future__ import annotations

import copy
import re
import unicodedata
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar, cast

from . import generator as synonym_generator

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

MAX_UNDO = 20  # Maximum undo steps

# ---------------------------------------------------------------------
# State (initialised in open_synonym_editor)
# ---------------------------------------------------------------------

DATA: Dict[str, Dict] = {}
INITIAL: Dict[str, Dict] = {}
undo_stack: List[Dict[str, object]] = []
redo_stack: List[Dict[str, object]] = []
current_lkns: List[str] = []
_lkn_refresh: Optional[Callable[[], None]] = None

save_callback: Optional[Callable[[Dict[str, List[str]], List[str]], None]] = None
on_generate: Optional[Callable[[str], None]] = None  # optional callback

root: Optional[tk.Tk | tk.Toplevel] = None
created_root: bool = False

status_var: Optional[tk.StringVar] = None

# Statisches Stub, damit Pylance nicht meckert. Zur Laufzeit kann ein echtes Objekt injiziert werden.
leistungskatalog_dict: Any | None = None

# Widgets der drei Sektionen – als dataclass mit Pflichtfeldern (eliminiert TypedDict-Warnungen)
@dataclass
class Section:
    lang: str
    count_current_var: tk.StringVar
    count_suggest_var: tk.StringVar
    current_listbox: tk.Listbox
    suggest_listbox: tk.Listbox
    entry_new: ttk.Entry

SECTIONS: Dict[str, Section] = {}  # lang -> widgets

T = TypeVar("T")

def _require(obj: Optional[T], name: str) -> T:
    if obj is None:
        raise RuntimeError(f"{name} not initialised. Call open_synonym_editor() first.")
    return obj

def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).lower()

# ---------------------------------------------------------------------
# Undo/Redo
# ---------------------------------------------------------------------

def save_state():
    state = {"data": copy.deepcopy(DATA), "lkns": list(current_lkns)}
    undo_stack.append(state)
    if len(undo_stack) > MAX_UNDO:
        undo_stack.pop(0)
    redo_stack.clear()

def undo():
    if not undo_stack:
        return
    redo_stack.append({"data": copy.deepcopy(DATA), "lkns": list(current_lkns)})
    state = undo_stack.pop()

    if isinstance(state, dict):
        data_state = state.get("data")
        lkn_state = state.get("lkns")
    else:
        data_state = state
        lkn_state = None

    DATA.clear()
    if isinstance(data_state, dict):
        DATA.update(data_state)
    render_all()

    current_lkns.clear()
    if isinstance(lkn_state, list):
        current_lkns.extend(lkn_state)
    if _lkn_refresh:
        try:
            _lkn_refresh()
        except Exception:
            pass

def redo():
    if not redo_stack:
        return
    undo_stack.append({"data": copy.deepcopy(DATA), "lkns": list(current_lkns)})
    state = redo_stack.pop()

    if isinstance(state, dict):
        data_state = state.get("data")
        lkn_state = state.get("lkns")
    else:
        data_state = state
        lkn_state = None

    DATA.clear()
    if isinstance(data_state, dict):
        DATA.update(data_state)
    render_all()

    current_lkns.clear()
    if isinstance(lkn_state, list):
        current_lkns.extend(lkn_state)
    if _lkn_refresh:
        try:
            _lkn_refresh()
        except Exception:
            pass

# ---------------------------------------------------------------------
# Operations (per language)
# ---------------------------------------------------------------------

def move_items(lang: str, items: List[str], from_list: str):
    d = DATA[lang]
    save_state()
    dup_msg = None
    if from_list == "suggest":
        for text in items:
            norm = normalize(text)
            if any(normalize(i["text"]) == norm for i in d["current"]):
                dup_msg = f"Bereits vorhanden: {text}"
                continue
            d["current"].append({"text": text})
            d["suggestions"] = [t for t in d["suggestions"] if normalize(t) != norm]
    else:
        for text in items:
            norm = normalize(text)
            d["suggestions"].append(text)
            d["current"] = [i for i in d["current"] if normalize(i["text"]) != norm]
    if dup_msg:
        set_status(dup_msg)
    render_lang(lang)

def _ask_string_dialog(
    title: str, prompt: str, initialvalue: str, parent: tk.Tk | tk.Toplevel
) -> str | None:
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()

    result = None

    def on_ok(event=None):
        nonlocal result
        result = entry.get()
        dialog.destroy()

    def on_cancel(event=None):
        dialog.destroy()

    ttk.Label(dialog, text=prompt).grid(row=0, column=0, padx=5, pady=5, sticky="w")

    entry_var = tk.StringVar(value=initialvalue)
    entry = ttk.Entry(dialog, textvariable=entry_var, width=80)
    entry.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
    entry.focus_set()
    entry.selection_range(0, tk.END)

    btn_frame = ttk.Frame(dialog)
    btn_frame.grid(row=2, column=0, padx=5, pady=5, sticky="e")

    ok_btn = ttk.Button(btn_frame, text="OK", command=on_ok)
    ok_btn.pack(side="left", padx=5)

    cancel_btn = ttk.Button(btn_frame, text="Abbrechen", command=on_cancel)
    cancel_btn.pack(side="left")

    dialog.bind("<Return>", on_ok)
    dialog.bind("<Escape>", on_cancel)

    parent.wait_window(dialog)
    return result

def edit_selected(lang: str):
    lb = _require(SECTIONS[lang].current_listbox, f"{lang}.current_listbox")
    sel = lb.curselection()
    if not sel:
        return
    idx = sel[0]
    old_text = lb.get(idx)
    new_text = _ask_string_dialog(
        "Bearbeiten",
        "Synonym:",
        initialvalue=old_text,
        parent=_require(root, "root"),
    )
    if new_text is None:
        return
    new_text = new_text.strip()
    if not new_text:
        set_status("Eintrag darf nicht leer sein")
        return
    if len(new_text) > 100:
        set_status("Eintrag zu lang")
        return
    norm = normalize(new_text)
    d = DATA[lang]
    if any(iidx != idx and normalize(i["text"]) == norm for iidx, i in enumerate(d["current"])):
        set_status("Bereits vorhanden")
        return
    save_state()
    d["current"][idx]["text"] = new_text
    render_lang(lang)

def add_new(lang: str, value: str):
    val = value.strip()
    if not val:
        set_status("Eintrag darf nicht leer sein")
        return
    if len(val) > 100:
        set_status("Eintrag zu lang")
        return
    d = DATA[lang]
    if any(normalize(i["text"]) == normalize(val) for i in d["current"]):
        set_status("Bereits vorhanden")
        return
    save_state()
    d["current"].append({"text": val})
    render_lang(lang)

def apply():
    global root, _lkn_refresh
    if save_callback:
        result = {lang: [i["text"] for i in DATA[lang]["current"]] for lang in DATA}
        save_callback(result, list(current_lkns))
    if root is not None:
        root.destroy()
    _lkn_refresh = None

def cancel():
    global root, _lkn_refresh
    DATA.clear()
    DATA.update(copy.deepcopy(INITIAL))
    undo_stack.clear()
    redo_stack.clear()
    current_lkns.clear()
    if root is not None:
        root.destroy()
    _lkn_refresh = None

def set_status(msg: str):
    if status_var is None:
        return
    status_var.set(msg)
    r = _require(root, "root")
    r.after(3000, lambda: status_var.set("") if status_var is not None and status_var.get() == msg else None)

# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------

def render_lang(lang: str):
    sec = SECTIONS[lang]
    clb = sec.current_listbox
    slb = sec.suggest_listbox

    d = DATA[lang]

    clb.delete(0, tk.END)
    for item in d["current"]:
        clb.insert(tk.END, item["text"])

    slb.delete(0, tk.END)
    for text in d["suggestions"]:
        slb.insert(tk.END, text)

    # Zähler
    sec.count_current_var.set(f"{clb.size()}/{len(d['current'])}")
    sec.count_suggest_var.set(f"{slb.size()}/{len(d['suggestions'])}")

    # Farbmarkierung
    cur_set = {normalize(i["text"]) for i in d["current"]}
    sug_set = {normalize(t) for t in d["suggestions"]}

    for idx in range(clb.size()):
        text = clb.get(idx)
        clb.itemconfig(idx, {"bg": "#ffe5e5" if normalize(text) not in sug_set else "white"})
    for idx in range(slb.size()):
        text = slb.get(idx)
        slb.itemconfig(idx, {"bg": "#e5e9ff" if normalize(text) not in cur_set else "white"})

def render_all():
    for lang in SECTIONS.keys():
        render_lang(lang)

# ---------------------------------------------------------------------
# Events (bound per section)
# ---------------------------------------------------------------------

def bind_section_handlers(lang: str, entry_new: ttk.Entry):
    sec = SECTIONS[lang]
    clb = sec.current_listbox
    slb = sec.suggest_listbox

    clb.bind("<Double-1>", lambda e, L=lang: on_double_click_current(e, L))
    slb.bind("<Double-1>", lambda e, L=lang: on_double_click_suggest(e, L))

    clb.bind("<Delete>", lambda e, L=lang: remove_selected(L))
    clb.bind("<F2>", lambda e, L=lang: edit_selected(L))
    entry_new.bind("<Return>", lambda e, L=lang, en=entry_new: (add_new(L, en.get()), en.delete(0, tk.END)))

def on_double_click_suggest(event, lang: str):
    lb = SECTIONS[lang].suggest_listbox
    indices = lb.curselection()
    if not indices:
        idx = lb.nearest(event.y)
        if idx >= 0:
            indices = (idx,)
    items = [lb.get(i) for i in indices]
    if items:
        move_items(lang, items, "suggest")

def on_double_click_current(event, lang: str):
    lb = SECTIONS[lang].current_listbox
    indices = lb.curselection()
    if not indices:
        idx = lb.nearest(event.y)
        if idx >= 0:
            indices = (idx,)
    items = [lb.get(i) for i in indices]
    if items:
        move_items(lang, items, "current")

def add_selected(lang: str):
    lb = SECTIONS[lang].suggest_listbox
    items = [lb.get(i) for i in lb.curselection()]
    move_items(lang, items, "suggest")

def add_all(lang: str):
    lb = SECTIONS[lang].suggest_listbox
    items = list(lb.get(0, tk.END))
    move_items(lang, items, "suggest")

def remove_selected(lang: str):
    lb = SECTIONS[lang].current_listbox
    items = [lb.get(i) for i in lb.curselection()]
    move_items(lang, items, "current")

def remove_all(lang: str):
    items = [i["text"] for i in DATA[lang]["current"]]
    move_items(lang, items, "current")

# ---------------------------------------------------------------------
# Description resolver (from global leistungskatalog_dict)
# ---------------------------------------------------------------------

def resolve_descriptions(lkn: Optional[str], desc_de: Optional[str]) -> Tuple[str, str, str]:
    """
    Try to get FR/IT descriptions from global leistungskatalog_dict.
    Returns (de, fr, it). Uses desc_de if provided; otherwise attempts lookup.
    Supported schemas:
        - leistungskatalog_dict[lkn]["beschreibung_de"/"beschreibung_fr"/"beschreibung_it"]
        - leistungskatalog_dict[lkn]["de"/"fr"/"it"]
        - list of dicts with keys {"lkn","de","fr","it"} or {"LKN","Beschreibung_de",...}
    """
    de = desc_de or ""
    fr = ""
    it = ""

    try:
        if lkn and leistungskatalog_dict is not None:
            data = leistungskatalog_dict

            if isinstance(data, dict) and lkn in data:
                node = data[lkn]
                if isinstance(node, dict):
                    de = cast(
                        str,
                        node.get("beschreibung_de")
                        or node.get("de")
                        or node.get("Beschreibung_de")
                        or node.get("Beschreibung")
                        or de,
                    )
                    fr = cast(
                        str,
                        node.get("beschreibung_fr")
                        or node.get("beschreibung_f")
                        or node.get("fr")
                        or node.get("Beschreibung_fr")
                        or node.get("Beschreibung_f")
                        or fr,
                    )
                    it = cast(
                        str,
                        node.get("beschreibung_it")
                        or node.get("beschreibung_i")
                        or node.get("it")
                        or node.get("Beschreibung_it")
                        or node.get("Beschreibung_i")
                        or it,
                    )
            elif isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    keys = {k.lower(): k for k in item.keys()}
                    k_lkn = keys.get("lkn")
                    if k_lkn and str(item[k_lkn]) == str(lkn):
                        de = cast(
                            str,
                            item.get(keys.get("beschreibung_de", ""))
                            or item.get(keys.get("de", ""))
                            or item.get(keys.get("beschreibung", ""))
                            or de,
                        )
                        fr = cast(
                            str,
                            item.get(keys.get("beschreibung_fr", ""))
                            or item.get(keys.get("fr", ""))
                            or fr,
                        )
                        it = cast(
                            str,
                            item.get(keys.get("beschreibung_it", ""))
                            or item.get(keys.get("it", ""))
                            or it,
                        )
                        break
    except Exception:
        pass

    return de or "", fr or "", it or ""

# ---------------------------------------------------------------------
# UI Builder
# ---------------------------------------------------------------------

def _build_section(parent: tk.Widget, lang: str, title_text: str, row_offset: int) -> ttk.Frame:
    """
    Builds one language section (two listboxes with transfer buttons).
    Layout per mockup.
    """
    sec_frame = ttk.Frame(parent)
    sec_frame.grid(row=row_offset, column=0, sticky="w", padx=0, pady=(6, 0))

    # Kopf der zwei Spalten-Zähler (links/ rechts)
    header = ttk.Frame(sec_frame)
    header.grid(row=0, column=0, sticky="w")

    # Linke Überschrift
    left_header = ttk.Frame(header)
    left_header.grid(row=0, column=0, sticky="w")
    ttk.Label(left_header, text="Aktuelle Synonyme").grid(row=0, column=0, sticky="w", padx=(0, 6))
    count_current_var = tk.StringVar(value="0/0")
    ttk.Label(left_header, textvariable=count_current_var).grid(row=0, column=1, sticky="w")

    # Rechte Überschrift
    right_header = ttk.Frame(header)
    right_header.grid(row=0, column=2, sticky="w", padx=(260, 0))  # Abstand wie Mockup
    ttk.Label(right_header, text="Vorschläge (auto)").grid(row=0, column=0, sticky="w", padx=(0, 6))
    count_suggest_var = tk.StringVar(value="0/0")
    ttk.Label(right_header, textvariable=count_suggest_var).grid(row=0, column=1, sticky="w")

    # Titelzeile Sprache (z.B. "DE:", "FR:", ... mit optionaler Zeile darüber)
    title = ttk.Label(sec_frame, text=title_text)
    title.grid(row=1, column=0, sticky="w", pady=(4, 2))

    # Hauptreihe mit drei Spalten
    row = ttk.Frame(sec_frame)
    row.grid(row=2, column=0, sticky="w")

    # Linke Listbox (current)
    left_frame = ttk.Frame(row)
    left_frame.grid(row=0, column=0, sticky="n")

    current_listbox = tk.Listbox(left_frame, selectmode=tk.EXTENDED, width=42, height=10)
    current_listbox.grid(row=0, column=0, sticky="nsew")
    current_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=current_listbox.yview)
    current_scroll.grid(row=0, column=1, sticky="ns")
    current_listbox.config(yscrollcommand=current_scroll.set)

    # Mittlere Buttons
    btn_frame = ttk.Frame(row)
    btn_frame.grid(row=0, column=1, padx=6, sticky="n")
    ttk.Button(btn_frame, text="<<", width=3, command=lambda L=lang: add_all(L)).grid(row=0, column=0, pady=2)
    ttk.Button(btn_frame, text="<",  width=3, command=lambda L=lang: add_selected(L)).grid(row=1, column=0, pady=2)
    ttk.Button(btn_frame, text=">",  width=3, command=lambda L=lang: remove_selected(L)).grid(row=2, column=0, pady=2)
    ttk.Button(btn_frame, text=">>", width=3, command=lambda L=lang: remove_all(L)).grid(row=3, column=0, pady=2)

    # Rechte Listbox (suggest)
    right_frame = ttk.Frame(row)
    right_frame.grid(row=0, column=2, sticky="n")

    suggest_listbox = tk.Listbox(right_frame, selectmode=tk.EXTENDED, width=42, height=10)
    suggest_listbox.grid(row=0, column=0, sticky="nsew")
    suggest_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=suggest_listbox.yview)
    suggest_scroll.grid(row=0, column=1, sticky="ns")
    suggest_listbox.config(yscrollcommand=suggest_scroll.set)

    # Eingabefeld "neu" (unterhalb der linken Box)
    entry_row = ttk.Frame(sec_frame)
    entry_row.grid(row=3, column=0, sticky="w", pady=(4, 0))
    entry_new = ttk.Entry(entry_row, width=40)
    entry_new.grid(row=0, column=0, sticky="w")
    ttk.Label(entry_row, text="  (Enter: hinzufügen, F2: bearbeiten, Entf: entfernen)").grid(row=0, column=1, sticky="w")

    # Save section refs
    section = Section(
        lang=lang,
        count_current_var=count_current_var,
        count_suggest_var=count_suggest_var,
        current_listbox=current_listbox,
        suggest_listbox=suggest_listbox,
        entry_new=entry_new,
    )
    SECTIONS[lang] = section

    # Bindings
    bind_section_handlers(lang, entry_new)

    return sec_frame

# ---------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------

def open_synonym_editor(
    data: Dict[str, Dict[str, List[str]] | Dict[str, List[Dict[str, str]]]],
    on_save: Optional[Callable[[Dict[str, List[str]], List[str]], None]] = None,
    master: Optional[tk.Tk | tk.Toplevel] = None,
    lkn: Optional[str] = None,
    lkns: Optional[List[str]] = None,
    beschreibung_de: Optional[str] = None,
    on_generate_callback: Optional[Callable[[str], None]] = None,
):
    """Open the synonym editor UI for the given data (DE/FR/IT sections)."""
    global DATA, INITIAL, undo_stack, redo_stack, save_callback, on_generate
    global root, created_root, status_var, SECTIONS, current_lkns, _lkn_refresh

    # Normalise incoming data: always dict[lang]["current"] as list[{"text": str}]
    normed: Dict[str, Dict] = {}
    for lang, payload in data.items():
        cur = payload.get("current", [])
        sug = payload.get("suggestions", [])
        cur_items: List[Dict[str, str]] = []
        for x in cur:
            if isinstance(x, dict) and "text" in x:
                cur_items.append({"text": str(x["text"])})
            else:
                cur_items.append({"text": str(x)})
        sug_items: List[str] = [str(s) for s in sug]
        normed[lang] = {"current": cur_items, "suggestions": sug_items}

    DATA = copy.deepcopy(normed)
    INITIAL = copy.deepcopy(normed)
    undo_stack = []
    redo_stack = []
    save_callback = on_save
    on_generate = on_generate_callback
    SECTIONS = {}

    normalized_codes: List[str] = []
    if lkns:
        for code in lkns:
            code_str = str(code).strip().upper()
            if code_str:
                normalized_codes.append(code_str)
    elif lkn:
        code_str = str(lkn).strip().upper()
        if code_str:
            normalized_codes.append(code_str)

    seen_codes: Set[str] = set()
    deduped_codes: List[str] = []
    for code_str in normalized_codes:
        if code_str not in seen_codes:
            seen_codes.add(code_str)
            deduped_codes.append(code_str)

    current_lkns.clear()
    current_lkns.extend(deduped_codes)

    # Resolve descriptions
    primary_lkn = current_lkns[0] if current_lkns else lkn
    de_desc, fr_desc, it_desc = resolve_descriptions(primary_lkn, beschreibung_de)

    lkn_display_var = cast(tk.StringVar, None)
    lkn_listbox = cast(tk.Listbox, None)
    entry_lkn_var = cast(tk.StringVar, None)

    def _normalize_code_input(value: str) -> List[str]:
        parts = [part for part in re.split(r"[|,;\s]+", value) if part]
        return [part.strip().upper() for part in parts if part.strip()]

    def refresh_lkn_widgets() -> None:
        display = ", ".join(current_lkns) if current_lkns else "-"
        lkn_display_var.set(display)
        lkn_listbox.delete(0, tk.END)
        for code in current_lkns:
            lkn_listbox.insert(tk.END, code)

    def add_lkn_from_entry(event: tk.Event | None = None) -> None:
        codes = _normalize_code_input(entry_lkn_var.get())
        codes = [code for code in codes if code and code not in current_lkns]
        if not codes:
            entry_lkn_var.set("")
            return
        save_state()
        current_lkns.extend(codes)
        refresh_lkn_widgets()
        entry_lkn_var.set("")

    def remove_selected_lkn(event: tk.Event | None = None) -> None:
        selection = list(lkn_listbox.curselection())
        if not selection:
            return
        save_state()
        for index in reversed(selection):
            code = lkn_listbox.get(index)
            if code in current_lkns:
                current_lkns.remove(code)
        refresh_lkn_widgets()
    # Synonym generation handler
    def handle_generate() -> None:
        base = {"de": de_desc}
        if fr_desc:
            base["fr"] = fr_desc
        if it_desc:
            base["it"] = it_desc
        try:
            # ``propose_synonyms_incremental`` returns an ``Iterable`` and not
            # an iterator, so calling ``next`` directly on it raises a type
            # checker warning.  Wrap it in ``iter`` to explicitly obtain an
            # iterator.
            entry = next(iter(synonym_generator.propose_synonyms_incremental([base])))
        except Exception:
            set_status("Generierung fehlgeschlagen")
            return
        save_state()
        for lang in ("de", "fr", "it"):
            cur_norm = {normalize(i["text"]) for i in DATA.get(lang, {}).get("current", [])}
            suggestions = [s for s in entry.by_lang.get(lang, []) if normalize(s) not in cur_norm]
            DATA.setdefault(lang, {"current": [], "suggestions": []})
            DATA[lang]["suggestions"] = suggestions
        render_all()
        set_status("Synonyme generiert")
        if on_generate:
            try:
                on_generate("de")
            except Exception:
                pass

    # Root
    if master is not None:
        root = tk.Toplevel(master)
        created_root = False
    else:
        root = tk.Tk()
        created_root = True

    r = _require(root, "root")
    r.title("Synonyme verwalten")
    r.protocol("WM_DELETE_WINDOW", cancel)

    # Button-Stil (grüne Umrandung dezent)
    try:
        style = ttk.Style()
        style.configure("Gen.TButton", borderwidth=2, relief="solid")
        style.map("Gen.TButton", relief=[("active", "solid")])
    except Exception:
        pass

    # Gesamtlayout
    container = ttk.Frame(r)
    container.grid(row=0, column=0, padx=10, pady=10, sticky="we")
    r.grid_columnconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)

    # Kopfzeile
    header = ttk.Frame(container)
    header.grid(row=0, column=0, sticky="we", pady=(0, 6))
    header.grid_columnconfigure(2, weight=1)

    ttk.Label(header, text="LKNs:").grid(row=0, column=0, sticky="w")
    lkn_display_var = tk.StringVar(value=", ".join(current_lkns) if current_lkns else "-")
    ttk.Label(header, textvariable=lkn_display_var).grid(row=0, column=1, sticky="w", padx=(4, 16))

    desc_text = de_desc or fr_desc or it_desc or "Keine Beschreibung hinterlegt"
    ttk.Label(
        header,
        text=desc_text,
        wraplength=500,
        justify="left",
    ).grid(row=0, column=2, sticky="w")

    gen_btn = ttk.Button(
        header,
        text="Synonyme generieren",
        command=handle_generate,
        style="Gen.TButton",
    )
    gen_btn.grid(row=0, column=3, padx=(24, 0), sticky="e")

    lkn_frame = ttk.Frame(container)
    lkn_frame.grid(row=1, column=0, sticky="we", pady=(0, 8))
    lkn_frame.grid_columnconfigure(1, weight=1)

    ttk.Label(lkn_frame, text="Verknuepfte LKNs:").grid(row=0, column=0, sticky="nw")

    lkn_listbox = tk.Listbox(lkn_frame, height=4, exportselection=False)
    lkn_listbox.grid(row=0, column=1, sticky="we")
    lkn_scroll = ttk.Scrollbar(lkn_frame, orient="vertical", command=lkn_listbox.yview)
    lkn_scroll.grid(row=0, column=2, sticky="ns")
    lkn_listbox.config(yscrollcommand=lkn_scroll.set)

    entry_lkn_var = tk.StringVar()
    entry_lkn = ttk.Entry(lkn_frame, textvariable=entry_lkn_var)
    entry_lkn.grid(row=1, column=1, sticky="we", pady=(4, 0))
    ttk.Button(lkn_frame, text="Hinzufuegen", command=add_lkn_from_entry).grid(row=1, column=2, padx=4, pady=(4, 0), sticky="e")
    ttk.Button(lkn_frame, text="Entfernen", command=remove_selected_lkn).grid(row=0, column=3, padx=(8, 0), sticky="n")

    entry_lkn.bind("<Return>", add_lkn_from_entry)
    lkn_listbox.bind("<Delete>", remove_selected_lkn)

    refresh_lkn_widgets()
    _lkn_refresh = refresh_lkn_widgets

    # DE-Sektion
    de_title = f"DE: {de_desc}" if de_desc else "DE:"
    _build_section(container, "de", de_title, row_offset=2)

    # Abstand
    ttk.Frame(container).grid(row=3, column=0, pady=(8, 0))

    # FR-Sektion
    fr_title = f"FR: {fr_desc}" if fr_desc else "FR:"
    _build_section(container, "fr", fr_title, row_offset=4)

    ttk.Frame(container).grid(row=5, column=0, pady=(8, 0))

    # IT-Sektion
    it_title = f"IT: {it_desc}" if it_desc else "IT:"
    _build_section(container, "it", it_title, row_offset=6)

    # Bottom buttons
    bottom = ttk.Frame(r)
    bottom.grid(row=1, column=0, pady=(10, 0), sticky="w")
    ttk.Button(bottom, text="Undo", command=undo).grid(row=0, column=0, padx=4)
    ttk.Button(bottom, text="Redo", command=redo).grid(row=0, column=1, padx=4)
    ttk.Button(bottom, text="Übernehmen", command=apply).grid(row=0, column=2, padx=12)
    ttk.Button(bottom, text="Abbrechen", command=cancel).grid(row=0, column=3, padx=4)

    # Statusleiste
    status_row = ttk.Frame(r)
    status_row.grid(row=2, column=0, sticky="w")
    status_var = tk.StringVar()
    ttk.Label(status_row, textvariable=status_var).grid(row=0, column=0, sticky="w", padx=10)

    # Shortcuts
    r.bind("<Control-z>", lambda e: undo())
    r.bind("<Control-y>", lambda e: redo())

    # Initial render
    render_all()

    if not created_root and master is not None:
        r.transient(master)
        r.grab_set()
        master.wait_window(r)
    elif created_root:
        cast(tk.Tk, r).mainloop()

# ---------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------

if __name__ == "__main__":
    sample_data = {
        "de": {"current": ["Arztbesuch", "Sprechstunde", "Arzttermin", "Erstgespräch", "Anamnesegespräch", "Konsultation", "Besuch beim Arzt"], "suggestions": []},
        "fr": {"current": ["Arztbesuch", "Sprechstunde", "Arzttermin", "Erstgespräch", "Anamnesegespräch", "Konsultation", "Besuch beim Arzt"], "suggestions": []},
        "it": {"current": ["Arztbesuch", "Sprechstunde", "Arzttermin", "Erstgespräch", "Anamnesegespräch", "Konsultation", "Besuch beim Arzt"], "suggestions": []},
    }
    # Für Demo: fallback-Katalog
    if leistungskatalog_dict is None:
        leistungskatalog_dict = {
            "AA.00.0010": {
                "beschreibung_de": "Ärztliche Konsultation, erste 5 Min.",
                "beschreibung_fr": "Consultation médicale, premières 5 min",
                "beschreibung_it": "Consulto medico, primi 5 min",
            }
        }
    open_synonym_editor(
        sample_data,
        lambda data, codes: print("Save", data, codes),
        lkns=["AA.00.0010"],
        beschreibung_de=None,
        on_generate_callback=lambda lang: print(f"Generate triggered for {lang.upper()}"),
    )


