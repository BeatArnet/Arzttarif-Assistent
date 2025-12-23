"""Utility helpers for boolean expression parsing and evaluation."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Sequence, Tuple

__all__ = [
    "compile_boolean_expression",
    "tokenize_boolean_expression",
    "shunting_yard",
    "evaluate_rpn",
    "evaluate_boolean_expression_safe",
]


def tokenize_boolean_expression(expression: str) -> List[str]:
    """Simple tokenizer for boolean expressions."""
    expr = expression.replace("(", " ( ").replace(")", " ) ")
    raw_tokens = expr.split()
    return [t.lower() if t.lower() in ("and", "or", "not") else t for t in raw_tokens]


def shunting_yard(tokens: List[str]) -> List[str]:
    """Convert infix boolean tokens to Reverse Polish Notation (RPN)."""
    output_queue: List[str] = []
    operator_stack: List[str] = []
    precedence = {"not": 3, "and": 2, "or": 1}

    for token in tokens:
        if token == "(":
            operator_stack.append(token)
        elif token == ")":
            while operator_stack and operator_stack[-1] != "(":
                output_queue.append(operator_stack.pop())
            if operator_stack and operator_stack[-1] == "(":
                operator_stack.pop()
        elif token in precedence:
            while (
                operator_stack
                and operator_stack[-1] != "("
                and precedence.get(operator_stack[-1], 0) >= precedence[token]
            ):
                output_queue.append(operator_stack.pop())
            operator_stack.append(token)
        else:
            output_queue.append(token)

    while operator_stack:
        output_queue.append(operator_stack.pop())

    return output_queue


def evaluate_rpn(rpn_queue: Sequence[str], context: Dict[str, bool]) -> bool:
    """Evaluate RPN queue."""
    stack: List[bool] = []

    for token in rpn_queue:
        if token == "and":
            val2 = stack.pop()
            val1 = stack.pop()
            stack.append(val1 and val2)
        elif token == "or":
            val2 = stack.pop()
            val1 = stack.pop()
            stack.append(val1 or val2)
        elif token == "not":
            val = stack.pop()
            stack.append(not val)
        else:
            lowered = token.lower()
            if lowered == "true":
                stack.append(True)
            elif lowered == "false":
                stack.append(False)
            else:
                stack.append(context.get(token, False))

    if not stack:
        return False
    return stack[0]


@lru_cache(maxsize=4096)
def compile_boolean_expression(expression: str) -> Tuple[str, ...]:
    """Compile an infix boolean expression into cached RPN tokens."""
    tokens = tokenize_boolean_expression(expression or "")
    return tuple(shunting_yard(tokens))


def evaluate_boolean_expression_safe(expression: str, context: Dict[str, bool]) -> bool:
    """Evaluate a boolean expression string with AND/OR/NOT and parentheses."""
    rpn_queue = compile_boolean_expression(expression or "")
    return evaluate_rpn(rpn_queue, context)
