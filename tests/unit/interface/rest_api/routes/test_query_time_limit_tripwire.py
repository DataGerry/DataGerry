# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
A census of the REST routes' time-limit answers, read with ``ast`` so it covers every route file

An ``except`` of a manager's iteration error answers a query the server stopped on its time budget with the shared
503 before anything else: its FIRST statement is ``abort_if_query_too_slow(<the error>)``. The shared error
decorators do it themselves; this is for the arms a route writes out. Every list route reads through the budgeted
pager, so every such arm can meet the time limit
"""
import ast
import re
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

ROUTES_ROOT: Path = Path(__file__).resolve().parents[5] / 'cmdb' / 'interface' / 'rest_api' / 'routes'
ITERATION_ERROR_PATTERN: re.Pattern[str] = re.compile(r'IterationError$')
GUARD: str = 'abort_if_query_too_slow'
# The hand-written arms there are - the census must not silently shrink. It is lowered only when an arm moves
# onto the shared error decorators, which answer the time limit themselves (the DocAPI template list did, and the
# user-settings list)
MIN_ARMS: int = 34


def _name(node: ast.expr) -> str:
    """The attribute or bare name an expression ends in"""
    if isinstance(node, ast.Attribute):
        return node.attr

    return node.id if isinstance(node, ast.Name) else ''


def _iteration_error_arms() -> list[tuple[str, int, ast.ExceptHandler]]:
    """Every except of a manager iteration error in the routes: (file, line, handler)"""
    found: list[tuple[str, int, ast.ExceptHandler]] = []

    for path in sorted(ROUTES_ROOT.rglob('*.py')):
        relative = str(path.relative_to(ROUTES_ROOT))

        for handler in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(handler, ast.ExceptHandler) or handler.type is None:
                continue

            caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]

            if any(ITERATION_ERROR_PATTERN.search(_name(entry)) for entry in caught):
                found.append((relative, handler.lineno, handler))

    return found


def _calls_the_guard_first(handler: ast.ExceptHandler) -> bool:
    """The handler's first statement is `abort_if_query_too_slow(<the caught error>)`"""
    first = handler.body[0]

    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Call)
        and _name(first.value.func) == GUARD
        and len(first.value.args) == 1
        and isinstance(first.value.args[0], ast.Name)
        and first.value.args[0].id == handler.name
    )


ARMS: list[tuple[str, int, ast.ExceptHandler]] = _iteration_error_arms()


def test_the_census_finds_the_arms() -> None:
    """Guards the census itself: a moved folder must not make the check vacuous"""
    assert len(ARMS) >= MIN_ARMS


@pytest.mark.parametrize('relative, line, handler', ARMS, ids=[f'{arm[0]}:{arm[1]}' for arm in ARMS])
def test_every_iteration_error_arm_answers_the_time_limit_first(
        relative: str, line: int, handler: ast.ExceptHandler) -> None:
    """Before it logs, maps or re-raises the failure its own way"""
    assert handler.name, f'{relative}:{line} binds no name, so it cannot hand the error over'
    assert _calls_the_guard_first(handler), f'{relative}:{line} does not start with {GUARD}'
