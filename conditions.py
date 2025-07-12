"""Wrapper module for core condition evaluation."""
from regelpruefer_pauschale import (
    DEFAULT_GROUP_OPERATOR,
    check_single_condition,
    get_group_operator_for_pauschale,
    evaluate_structured_conditions,
)

__all__ = [
    "DEFAULT_GROUP_OPERATOR",
    "check_single_condition",
    "get_group_operator_for_pauschale",
    "evaluate_structured_conditions",
]
