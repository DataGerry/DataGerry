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
A census of the REST routes' size-limit answers, read with ``ast`` so it covers every route file

Two rules, each a line a new route has to remember:

  - an ``except`` of a manager's insert / update error answers a write refused on MongoDB's 16 MB limit with the
    shared 400 before anything else: its FIRST statement is ``abort_if_too_large(<the error>)``. The shared error
    decorators do it themselves; this is for the arms a route writes out
  - a route that reads an upload from the request carries ``accepts_upload``, or its body is held to the JSON
    limit and a real upload is refused with a 413

An arm that must not answer the size limit has to be listed here with its reason
"""
import ast
import re
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

ROUTES_ROOT: Path = Path(__file__).resolve().parents[5] / 'cmdb' / 'interface' / 'rest_api' / 'routes'
WRITE_ERROR_PATTERN: re.Pattern[str] = re.compile(r'Manager(Insert|Update)Error$')
GUARD: str = 'abort_if_too_large'
UPLOAD_DECORATOR: str = 'accepts_upload'

# Names whose use in a route body means the route reads an upload
UPLOAD_READERS: frozenset[str] = frozenset({
    'files', 'form', 'get_file_in_request', 'get_upload_from_request', 'run_type_import_request',
})

# (route file relative to ROUTES_ROOT, enclosing function) -> why its arm does not answer the size limit
EXEMPT_ARMS: dict[tuple[str, str], str] = {
    ('relation_routes/relations_helper.py', 'log_object_relation_change'):
        'a failed change-log entry is logged and swallowed after the write it records succeeded',
    ('importer_routes/importer_isms_routes.py', 'insert_or_reuse_extendable_option'):
        'resolves a lost duplicate race by re-reading; an option value is held to its schema',
}


def _name(node: ast.expr) -> str:
    """The attribute or bare name an expression ends in"""
    if isinstance(node, ast.Attribute):
        return node.attr

    return node.id if isinstance(node, ast.Name) else ''


def _write_error_arms() -> list[tuple[str, str, ast.ExceptHandler]]:
    """Every except of a manager insert / update error in the routes: (file, enclosing function, handler)"""
    found: dict[tuple[str, int], tuple[str, str, ast.ExceptHandler]] = {}

    for path in sorted(ROUTES_ROOT.rglob('*.py')):
        relative = str(path.relative_to(ROUTES_ROOT))

        for function in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            for handler in ast.walk(function):
                if not isinstance(handler, ast.ExceptHandler) or handler.type is None:
                    continue

                caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]

                if any(WRITE_ERROR_PATTERN.search(_name(entry)) for entry in caught):
                    # The innermost function wins: ast.walk visits it after the one enclosing it
                    found[(relative, handler.lineno)] = (relative, function.name, handler)

    return list(found.values())


def _calls_the_guard_first(handler: ast.ExceptHandler) -> bool:
    """The handler's first statement is `abort_if_too_large(<the caught error>)`"""
    first = handler.body[0]

    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Call)
        and _name(first.value.func) == GUARD
        and len(first.value.args) == 1
        and isinstance(first.value.args[0], ast.Name)
        and first.value.args[0].id == handler.name
    )


def _routes() -> list[tuple[str, ast.FunctionDef]]:
    """Every route function: (file, node)"""
    found: list[tuple[str, ast.FunctionDef]] = []

    for path in sorted(ROUTES_ROOT.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.FunctionDef) and any(
                    _name(decorator.func if isinstance(decorator, ast.Call) else decorator) == 'route'
                    for decorator in node.decorator_list):
                found.append((str(path.relative_to(ROUTES_ROOT)), node))

    return found


ARMS: list[tuple[str, str, ast.ExceptHandler]] = _write_error_arms()
ROUTES: list[tuple[str, ast.FunctionDef]] = _routes()


def test_the_census_finds_the_arms_and_the_routes() -> None:
    """Guards the census itself: a moved folder must not make every check vacuous"""
    assert len(ARMS) > 60
    assert len(ROUTES) > 300


@pytest.mark.parametrize('relative, function, handler', ARMS, ids=lambda value: getattr(value, 'lineno', value))
def test_every_write_error_arm_answers_the_size_limit_first(
        relative: str, function: str, handler: ast.ExceptHandler) -> None:
    """Before it logs, maps or re-raises the failure its own way"""
    if (relative, function) in EXEMPT_ARMS:
        pytest.skip(EXEMPT_ARMS[(relative, function)])

    assert handler.name, f'{relative}:{handler.lineno} binds no name, so it cannot hand the error over'
    assert _calls_the_guard_first(handler), f'{relative}:{handler.lineno} ({function}) does not start with {GUARD}'


def test_every_exemption_still_exists() -> None:
    """A stale entry would silently exempt the next arm written in that function"""
    present = {(relative, function) for relative, function, _ in ARMS}

    assert set(EXEMPT_ARMS) <= present


def test_every_route_reading_an_upload_accepts_one() -> None:
    """A route that reads request.files / request.form, or an upload helper, raises its own limit"""
    missing: list[str] = []

    for relative, route in ROUTES:
        reads_upload = any(
            isinstance(node, (ast.Attribute, ast.Name)) and _name(node) in UPLOAD_READERS
            for node in ast.walk(route)
        )
        decorators = {_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
                      for decorator in route.decorator_list}

        if reads_upload and UPLOAD_DECORATOR not in decorators:
            missing.append(f'{relative}:{route.name}')

    assert not missing


def test_the_upload_routes_are_the_known_seven() -> None:
    """Guards the reader set: the census must actually see the routes it was written for"""
    carrying = sorted(
        f'{relative}:{route.name}' for relative, route in ROUTES
        if UPLOAD_DECORATOR in {_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
                                for decorator in route.decorator_list}
    )

    assert carrying == [
        'importer_routes/importer_isms_routes.py:import_isms_objects',
        'importer_routes/importer_object_routes.py:import_objects',
        'importer_routes/importer_object_routes.py:parse_objects',
        'importer_routes/importer_type_routes.py:add_type',
        'importer_routes/importer_type_routes.py:update_type',
        'media_library_routes/media_file_routes.py:add_new_file',
        'media_library_routes/media_file_routes.py:update_file',
    ]
