"""Tkinter-based synonym editor used from the synonym list window.

The editor is opened per LKN to manage multilingual synonym sets. Use
``open_synonym_editor`` to display the dialog within the existing
application window.
"""

import tkinter as tk
from tkinter import ttk, simpledialog
import unicodedata
import copy
from typing import Callable, Any

# Maximum undo steps
MAX_UNDO = 20

# Runtime state is initialised when ``open_synonym_editor`` is called.
DATA: dict[str, dict] = {}
INITIAL: dict[str, dict] = {}
FILTERS: dict[str, dict] = {}
undo_stack: list = []
redo_stack: list = []

active_lang = "de"
active_list = "current"
save_callback: Callable[[dict[str, list[str]]], Any] | None = None
root: tk.Misc | None = None


def normalize(text: str) -> str:
    """Normalize a string for comparison."""
    return unicodedata.normalize("NFC", text.strip()).lower()


def save_state():
    undo_stack.append(copy.deepcopy(DATA))
    if len(undo_stack) > MAX_UNDO:
        undo_stack.pop(0)
    redo_stack.clear()


def undo():
    if not undo_stack:
        return
    redo_stack.append(copy.deepcopy(DATA))
    state = undo_stack.pop()
    DATA.clear()
    DATA.update(state)
    render()


def redo():
    if not redo_stack:
        return
    undo_stack.append(copy.deepcopy(DATA))
    state = redo_stack.pop()
    DATA.clear()
    DATA.update(state)
    render()


def move_items(items, from_list):
    d = DATA[active_lang]
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
    render()


def edit_selected():
    sel = current_listbox.curselection()
    if not sel:
        return
    idx = sel[0]
    old_text = current_listbox.get(idx)
    new_text = simpledialog.askstring("Bearbeiten", "Synonym:", initialvalue=old_text)
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
    d = DATA[active_lang]
    if any(iidx != idx and normalize(i["text"]) == norm for iidx, i in enumerate(d["current"])):
        set_status("Bereits vorhanden")
        return
    save_state()
    d["current"][idx]["text"] = new_text
    render()


def add_new(event=None):
    val = new_var.get().strip()
    if not val:
        set_status("Eintrag darf nicht leer sein")
        return
    if len(val) > 100:
        set_status("Eintrag zu lang")
        return
    d = DATA[active_lang]
    if any(normalize(i["text"]) == normalize(val) for i in d["current"]):
        set_status("Bereits vorhanden")
        return
    save_state()
    d["current"].append({"text": val})
    new_var.set("")
    render()


def apply():
    """Persist the current state via callback and close the window."""
    global root
    if save_callback:
        result = {
            lang: sorted(i["text"] for i in DATA[lang]["current"])
            for lang in DATA
        }
        save_callback(result)
    if root is not None:
        root.destroy()
        # reset global handle to avoid stale Optional access
        root = None


def cancel():
    """Close the editor without persisting changes."""
    global root
    DATA.clear()
    DATA.update(copy.deepcopy(INITIAL))
    undo_stack.clear()
    redo_stack.clear()
    if root is not None:
        root.destroy()
        root = None


def set_status(msg):
    status_var.set(msg)
    if root is not None:
        root.after(3000, lambda: status_var.set("") if status_var.get() == msg else None)


def on_filter_change(*_):
    FILTERS[active_lang]["current"] = filter_cur_var.get()
    FILTERS[active_lang]["suggest"] = filter_sug_var.get()
    render()


def render():
    d = DATA[active_lang]
    f_cur = FILTERS[active_lang]["current"].lower()
    f_sug = FILTERS[active_lang]["suggest"].lower()

    current_listbox.delete(0, tk.END)
    for item in d["current"]:
        if f_cur and f_cur not in item["text"].lower():
            continue
        current_listbox.insert(tk.END, item["text"])

    suggest_listbox.delete(0, tk.END)
    for text in d["suggestions"]:
        if f_sug and f_sug not in text.lower():
            continue
        suggest_listbox.insert(tk.END, text)

    # Update counts
    count_current_var.set(f"{current_listbox.size()}/{len(d['current'])}")
    count_suggest_var.set(f"{suggest_listbox.size()}/{len(d['suggestions'])}")

    # Color differences
    cur_set = {normalize(i["text"]) for i in d["current"]}
    sug_set = {normalize(t) for t in d["suggestions"]}
    for idx in range(current_listbox.size()):
        text = current_listbox.get(idx)
        if normalize(text) not in sug_set:
            current_listbox.itemconfig(idx, {"bg": "#ffe5e5"})
        else:
            current_listbox.itemconfig(idx, {"bg": "white"})
    for idx in range(suggest_listbox.size()):
        text = suggest_listbox.get(idx)
        if normalize(text) not in cur_set:
            suggest_listbox.itemconfig(idx, {"bg": "#e5e9ff"})
        else:
            suggest_listbox.itemconfig(idx, {"bg": "white"})


def on_lang_change(event=None):
    global active_lang
    active_lang = lang_var.get()
    filter_cur_var.set(FILTERS[active_lang]["current"])
    filter_sug_var.set(FILTERS[active_lang]["suggest"])
    render()


def on_double_click_suggest(event):
    indices = suggest_listbox.curselection()
    if not indices:
        idx = suggest_listbox.nearest(event.y)
        if idx >= 0:
            indices = (idx,)
    items = [suggest_listbox.get(i) for i in indices]
    if items:
        move_items(items, "suggest")


def on_double_click_current(event):
    indices = current_listbox.curselection()
    if not indices:
        idx = current_listbox.nearest(event.y)
        if idx >= 0:
            indices = (idx,)
    items = [current_listbox.get(i) for i in indices]
    if items:
        move_items(items, "current")


def add_selected():
    items = [suggest_listbox.get(i) for i in suggest_listbox.curselection()]
    move_items(items, "suggest")


def add_all():
    items = list(suggest_listbox.get(0, tk.END))
    move_items(items, "suggest")


def remove_selected():
    items = [current_listbox.get(i) for i in current_listbox.curselection()]
    move_items(items, "current")


def remove_all():
    items = [i["text"] for i in DATA[active_lang]["current"]]
    move_items(items, "current")


def focus_filter(event=None):
    if active_list == "current":
        filter_current.focus_set()
    else:
        filter_suggest.focus_set()


def set_active_list(name):
    global active_list
    active_list = name


def open_synonym_editor(data, on_save=None, master=None):
    """Open the synonym editor UI for the given data.

    Args:
        data: Mapping language -> {"current": [...], "suggestions": [...]}.
        on_save: Callback invoked with the resulting data after "Übernehmen".
        master: Optional parent widget; if ``None`` a new root window is created.
    """
    global DATA, INITIAL, FILTERS, undo_stack, redo_stack, active_lang, active_list
    global save_callback, root
    global lang_var, lang_menu, main_frame, left_frame, count_current_var
    global filter_cur_var, filter_current, current_listbox, current_scroll
    global new_var, new_entry, btn_frame, right_frame, count_suggest_var
    global filter_sug_var, filter_suggest, suggest_listbox, suggest_scroll
    global bottom_frame, status_var, status_label

    DATA = copy.deepcopy(data)
    INITIAL = copy.deepcopy(data)
    FILTERS = {lang: {"current": "", "suggest": ""} for lang in DATA}
    undo_stack = []
    redo_stack = []
    active_lang = next(iter(DATA.keys())) if DATA else ""
    active_list = "current"
    save_callback = on_save

    root = tk.Toplevel(master) if master else tk.Tk()
    root.title("Synonyme verwalten")

    lang_var = tk.StringVar(value=active_lang)
    lang_menu = ttk.Combobox(root, textvariable=lang_var, values=list(DATA.keys()), state="readonly")
    lang_menu.grid(row=0, column=0, padx=5, pady=5, sticky="w")
    lang_menu.bind("<<ComboboxSelected>>", on_lang_change)

    main_frame = ttk.Frame(root)
    main_frame.grid(row=1, column=0, padx=5, pady=5)

    # Left list (current)
    left_frame = ttk.Frame(main_frame)
    left_frame.grid(row=0, column=0)

    ttk.Label(left_frame, text="Aktuelle Synonyme").grid(row=0, column=0)
    count_current_var = tk.StringVar(value="0/0")
    ttk.Label(left_frame, textvariable=count_current_var).grid(row=0, column=1)
    filter_cur_var = tk.StringVar()
    filter_current = ttk.Entry(left_frame, textvariable=filter_cur_var)
    filter_current.grid(row=1, column=0, columnspan=2, sticky="ew")
    filter_cur_var.trace_add("write", on_filter_change)
    current_listbox = tk.Listbox(left_frame, selectmode=tk.EXTENDED, width=30, height=20)
    current_listbox.grid(row=2, column=0, columnspan=2, sticky="nsew")
    current_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=current_listbox.yview)
    current_scroll.grid(row=2, column=2, sticky="ns")
    current_listbox.config(yscrollcommand=current_scroll.set)
    current_listbox.bind("<Double-1>", on_double_click_current)
    current_listbox.bind("<Delete>", lambda e: remove_selected())
    current_listbox.bind("<F2>", lambda e: edit_selected())
    current_listbox.bind("<FocusIn>", lambda e: set_active_list("current"))

    new_var = tk.StringVar()
    new_entry = ttk.Entry(left_frame, textvariable=new_var)
    new_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5,0))
    new_entry.bind("<Return>", add_new)

    # Buttons
    btn_frame = ttk.Frame(main_frame)
    btn_frame.grid(row=0, column=1, padx=5)

    ttk.Button(btn_frame, text="<<", command=add_all).grid(row=0, column=0, pady=2)
    ttk.Button(btn_frame, text="<", command=add_selected).grid(row=1, column=0, pady=2)
    ttk.Button(btn_frame, text=">", command=remove_selected).grid(row=2, column=0, pady=2)
    ttk.Button(btn_frame, text=">>", command=remove_all).grid(row=3, column=0, pady=2)

    # Right list (suggestions)
    right_frame = ttk.Frame(main_frame)
    right_frame.grid(row=0, column=2)

    ttk.Label(right_frame, text="Vorschläge (auto)").grid(row=0, column=0)
    count_suggest_var = tk.StringVar(value="0/0")
    ttk.Label(right_frame, textvariable=count_suggest_var).grid(row=0, column=1)
    filter_sug_var = tk.StringVar()
    filter_suggest = ttk.Entry(right_frame, textvariable=filter_sug_var)
    filter_suggest.grid(row=1, column=0, columnspan=2, sticky="ew")
    filter_sug_var.trace_add("write", on_filter_change)

    suggest_listbox = tk.Listbox(right_frame, selectmode=tk.EXTENDED, width=30, height=20)

    suggest_listbox.grid(row=2, column=0, columnspan=2, sticky="nsew")

    suggest_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=suggest_listbox.yview)

    suggest_scroll.grid(row=2, column=2, sticky="ns")

    suggest_listbox.config(yscrollcommand=suggest_scroll.set)

    suggest_listbox.bind("<Double-1>", on_double_click_suggest)

    suggest_listbox.bind("<Return>", lambda e: add_selected())

    suggest_listbox.bind("<FocusIn>", lambda e: set_active_list("suggest"))

    # Bottom buttons
    bottom_frame = ttk.Frame(root)
    bottom_frame.grid(row=2, column=0, pady=5)

    ttk.Button(bottom_frame, text="Undo", command=undo).grid(row=0, column=0, padx=2)
    ttk.Button(bottom_frame, text="Redo", command=redo).grid(row=0, column=1, padx=2)
    ttk.Button(bottom_frame, text="Übernehmen", command=apply).grid(row=0, column=2, padx=2)
    ttk.Button(bottom_frame, text="Abbrechen", command=cancel).grid(row=0, column=3, padx=2)

    status_var = tk.StringVar()
    status_label = ttk.Label(root, textvariable=status_var)
    status_label.grid(row=3, column=0, sticky="w", padx=5)

    root.bind("<Control-z>", lambda e: undo())
    root.bind("<Control-y>", lambda e: redo())
    root.bind("<Control-f>", focus_filter)

    on_lang_change()
    render()

    if master:
        root.transient(master)
        root.grab_set()
        master.wait_window(root)
    else:
        root.mainloop()


if __name__ == "__main__":
    sample_data = {
        "de": {"current": [], "suggestions": ["Beispiel", "Synonym"]},
        "fr": {"current": [], "suggestions": []},
        "it": {"current": [], "suggestions": []},
    }
    open_synonym_editor(sample_data, lambda data: print("Save", data))
