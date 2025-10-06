"""Minimaler Flask-Blueprint mit Synonym-Endpunkten.

Die API dient während der Entwicklung als schneller Vertragstest für den
Synonym-Service; im Produktivbetrieb kommuniziert der Browser mit dem
Haupt-Server. Um Abhängigkeiten gering zu halten, liefern wir Stubs, falls
Flask fehlt – so lassen sich die restlichen Pakete auch ohne optionale
GUI-Komponenten importieren.
"""

from __future__ import annotations
from typing import Any

try:
    # When Flask is available we import ``Blueprint`` under the alias
    # ``FlaskBlueprint`` so that type checkers see the same type that
    # ``server.py`` expects when registering the blueprint.
        from flask import Blueprint, jsonify, request
        FlaskBlueprint = Blueprint  # type: ignore[assignment]
except ModuleNotFoundError:  # pragma: no cover - minimal stubs
    # Laufzeit-Stubs bereitstellen, damit CLI-Werkzeuge das Modul ohne Flask laden können.
    class FlaskBlueprint:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def route(self, *a: Any, **kw: Any):
            def decorator(func):
                return func
            return decorator

    def jsonify(obj: Any = None) -> Any:  # type: ignore
        return obj

    class _Request:
        is_json = False

        def get_json(self, silent: bool = False) -> Any:
            return {}

    request = _Request()  # type: ignore
else:
    # import succeeded, Blueprint is provided by Flask
    pass

bp = FlaskBlueprint("synonyms", __name__, url_prefix="/api/synonyms")


@bp.route("/", methods=["GET"])
def root() -> Any:
    """Einfacher Bereitschaftsendpunkt."""
    return jsonify({"status": "ok"})


@bp.route("/suggest", methods=["POST"])
def suggest() -> Any:
    """Gibt den erhaltenen Payload als Vorschlag zurück (Entwicklungshilfe)."""
    data = request.get_json(silent=True) or {}
    return jsonify({"suggest": data})


@bp.route("/<concept_id>/status", methods=["PATCH"])
def update_status(concept_id: str) -> Any:
    """Aktualisiert den Status eines Synonym-Konzepts (Stub)."""
    data = request.get_json(silent=True) or {}
    return jsonify({"concept_id": concept_id, "status": data})


@bp.route("/<concept_id>/synonyms", methods=["POST"])
def add_synonym(concept_id: str) -> Any:
    """Fügt einem Konzept Synonyme hinzu (Stub)."""
    data = request.get_json(silent=True) or {}
    return jsonify({"concept_id": concept_id, "added": data})


@bp.route("/<concept_id>/synonyms", methods=["DELETE"])
def delete_synonym(concept_id: str) -> Any:
    """Markiert ein Synonym als gelöscht (Stub)."""
    return jsonify({"concept_id": concept_id, "deleted": True})
