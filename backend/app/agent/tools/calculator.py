"""Safe arithmetic evaluator built on the `ast` module — no eval(), no names."""

import ast
import operator
from typing import Any

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_MAX_POW = 10_000


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW:
            raise ValueError("exponent too large")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


def run_calculator(args: dict[str, Any], _seed: int) -> dict[str, Any]:
    expression = str(args.get("expression", "")).strip()
    if not expression:
        raise ValueError("expression is required")
    if len(expression) > 500:
        raise ValueError("expression too long")
    tree = ast.parse(expression, mode="eval")
    result = _eval_node(tree)
    # Normalise -0.0 and float noise for stable diffs.
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return {"expression": expression, "result": result}
