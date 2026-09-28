"""
backend/tools/implementations/calculator.py — safe arithmetic (Phase 5, READ).
═══════════════════════════════════════════════════════════════════════════════
No eval()/exec(). The expression is parsed to an AST and walked node-by-node; only
an explicit whitelist of node types, operators and functions is permitted. Anything
else (names, attribute access, calls to unknown functions, comprehensions, etc.) is
rejected. This is the standard "safe calculator" pattern.

Allowed: + - * / // % **  and unary +/- ; functions sqrt, log, round.
"""
from __future__ import annotations

import ast
import math
import operator

from ..base import BaseTool, ToolPermission, ToolResult

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "log": math.log, "round": round}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("only numeric constants are allowed")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"operator {type(node.op).__name__} not allowed")
        return op(_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unary operator {type(node.op).__name__} not allowed")
        return op(_eval(node.operand))
    if isinstance(node, ast.Call):
        # only bare function names from the whitelist (no math.sqrt attribute chains,
        # no keyword args), so there's no path to arbitrary attributes/callables.
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("only sqrt(), log(), round() may be called")
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError(f"disallowed expression element: {type(node).__name__}")


class CalculatorTool(BaseTool):
    name = "calculator"
    description = ("Evaluate a math expression safely (+ - * / // % **, and sqrt/log/round). "
                   "No variables, no arbitrary code.")
    permission = ToolPermission.READ
    schema = {"type": "object",
              "properties": {"expression": {"type": "string"}},
              "required": ["expression"]}

    def _run(self, args: dict) -> ToolResult:
        expr = (args.get("expression") or "").strip()
        if not expr:
            return ToolResult.fail("no 'expression' provided")
        try:
            tree = ast.parse(expr, mode="eval")
            value = _eval(tree)
        except ZeroDivisionError:
            return ToolResult.fail("division by zero")
        except (ValueError, SyntaxError, TypeError) as e:
            return ToolResult.fail(f"invalid expression: {e}")
        return ToolResult.success({"expression": expr, "result": value})
