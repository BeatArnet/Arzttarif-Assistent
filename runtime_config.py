"""Helper-Funktionen, um statische und dynamische Konfiguration zu trennen.

Die Anwendung liest weiterhin ``config.ini`` als Basis. Laufzeitwerte wie
Fensterpositionen oder erkannte Modellfähigkeiten werden hingegen in
``config.runtime.ini`` gespeichert. So bleiben Kommentare in der Hauptdatei
erhalten und Versionsstände lassen sich sauber nachverfolgen.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Dict

CONFIG_MAIN_PATH = Path(__file__).resolve().parent / "config.ini"
CONFIG_RUNTIME_PATH = Path(__file__).resolve().parent / "config.runtime.ini"


def load_base_config() -> configparser.ConfigParser:
    """Lädt ausschließlich die statische Grundkonfiguration."""
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_MAIN_PATH, encoding="utf-8-sig")
    return cfg


def load_runtime_config() -> configparser.ConfigParser:
    """Lädt nur die dynamische Laufzeitkonfiguration."""
    cfg = configparser.ConfigParser()
    if CONFIG_RUNTIME_PATH.exists():
        cfg.read(CONFIG_RUNTIME_PATH, encoding="utf-8-sig")
    return cfg


def load_merged_config() -> configparser.ConfigParser:
    """Kombiniert statische und dynamische Konfiguration."""
    base = load_base_config()
    runtime = load_runtime_config()
    for section in runtime.sections():
        if not base.has_section(section):
            base.add_section(section)
        for key, value in runtime.items(section):
            base.set(section, key, value)
    return base


def save_runtime_config(cfg: configparser.ConfigParser) -> None:
    """Persistiert die Laufzeitdaten in ``config.runtime.ini``."""
    CONFIG_RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_RUNTIME_PATH.open("w", encoding="utf-8") as fh:
        cfg.write(fh)


def update_runtime_section(section: str, updates: Dict[str, str]) -> None:
    """Aktualisiert gezielt ein Konfigurations-Teilsegment."""
    cfg = load_runtime_config()
    if not cfg.has_section(section):
        cfg.add_section(section)
    for key, value in updates.items():
        cfg.set(section, key, value)
    save_runtime_config(cfg)
