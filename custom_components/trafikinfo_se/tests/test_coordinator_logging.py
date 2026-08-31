"""Regression tests for privacy-safe coordinator logging."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


class CoordinatorLoggingPrivacyTest(unittest.TestCase):
    """Ensure precise Home Assistant coordinates never reach log calls."""

    def test_log_calls_do_not_receive_precise_coordinates(self) -> None:
        source_path = Path(__file__).parents[1] / "coordinator.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        sensitive_log_arguments: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"debug", "info", "warning", "error", "exception"}:
                continue
            for argument in node.args[1:]:
                rendered = ast.unparse(argument)
                if rendered in {"self._latitude", "self._longitude"}:
                    sensitive_log_arguments.append(rendered)

        self.assertEqual([], sensitive_log_arguments)


if __name__ == "__main__":
    unittest.main()
