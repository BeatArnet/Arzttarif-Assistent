from __future__ import annotations
from typing import Any

try:
    # When Flask is available we import ``Blueprint`` under the alias
    # ``FlaskBlueprint`` so that type checkers see the same type that
    # ``server.py`` expects when registering the blueprint.
        from flask import Blueprint, jsonify, request
        FlaskBlueprint = Blueprint  # type: ignore[assignment]
except ModuleNotFoundError:  # pragma: no cover - minimal stubs
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
    """Basic readiness endpoint."""
    return jsonify({"status": "ok"})


@bp.route("/suggest", methods=["POST"])
def suggest() -> Any:
    data = request.get_json(silent=True) or {}
    return jsonify({"suggest": data})


@bp.route("/<concept_id>/status", methods=["PATCH"])
def update_status(concept_id: str) -> Any:
    data = request.get_json(silent=True) or {}
    return jsonify({"concept_id": concept_id, "status": data})


@bp.route("/<concept_id>/synonyms", methods=["POST"])
def add_synonym(concept_id: str) -> Any:
    data = request.get_json(silent=True) or {}
    return jsonify({"concept_id": concept_id, "added": data})


@bp.route("/<concept_id>/synonyms", methods=["DELETE"])
def delete_synonym(concept_id: str) -> Any:
    return jsonify({"concept_id": concept_id, "deleted": True})
