# DATAGERRY - OpenSource Enterprise CMDB
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
The ``request_user`` exemption from pylint's ``unused-argument`` check, and what keeps it honest

``.pylintrc`` exempts the argument name ``request_user`` repo-wide, because ``@insert_request_user`` -
the decorator that authenticates a route - injects the user under exactly that keyword, so a handler
that never reads it still has to accept it. The exemption is a name rule, and a name rule cannot tell a
decorated route from any other function. This module restores the distinction by reading the source:

* the exemption matches ``request_user`` and nothing else, and the default exemptions are still there
* **an unread ``request_user`` parameter is only legal on a function ``@insert_request_user`` wraps** -
  anywhere else the argument is genuinely unused, which is exactly what the lint check exists to report

DB-free and import-free: the tree under ``cmdb/`` is parsed with ``ast``, never imported
"""
import ast
import configparser
import re
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
PYLINTRC: Path = REPO_ROOT / '.pylintrc'
CMDB_ROOT: Path = REPO_ROOT / 'cmdb'

EXEMPT_NAME: str = 'request_user'
INJECTING_DECORATOR: str = 'insert_request_user'

# A route whose handler never reads the user - if the scan stops finding it, the scan is broken
KNOWN_UNREAD_ROUTE: tuple[str, str] = (
    'cmdb/interface/rest_api/routes/config_routes/config_file_routes.py', 'get_oc_config_status',
)


def _ignored_argument_pattern() -> re.Pattern[str]:
    """The ``ignored-argument-names`` expression, as pylint reads it from ``.pylintrc``."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PYLINTRC, encoding='utf-8')

    for section in parser.sections():
        if parser.has_option(section, 'ignored-argument-names'):
            return re.compile(parser.get(section, 'ignored-argument-names'))

    raise AssertionError('.pylintrc declares no ignored-argument-names')


def _decorator_name(decorator: ast.expr) -> str | None:
    """The bare name of a decorator: ``@name``, ``@module.name`` or ``@name(...)``."""
    target: ast.expr = decorator.func if isinstance(decorator, ast.Call) else decorator

    if isinstance(target, ast.Name):
        return target.id

    if isinstance(target, ast.Attribute):
        return target.attr

    return None


def _parameter_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every parameter name of a function, of every kind."""
    arguments = function.args
    names: list[ast.arg] = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]

    if arguments.vararg:
        names.append(arguments.vararg)

    if arguments.kwarg:
        names.append(arguments.kwarg)

    return {argument.arg for argument in names}


def _reads_name(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """Whether the function body loads ``name`` anywhere, nested scopes included."""
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
        for statement in function.body
        for node in ast.walk(statement)
    )


def _unread_request_user_functions() -> list[tuple[str, str, bool]]:
    """(path, function, wrapped by insert_request_user) for every function that never reads its request_user."""
    found: list[tuple[str, str, bool]] = []

    for path in sorted(CMDB_ROOT.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            if EXEMPT_NAME not in _parameter_names(node) or _reads_name(node, EXEMPT_NAME):
                continue

            wrapped: bool = any(_decorator_name(decorator) == INJECTING_DECORATOR for decorator in node.decorator_list)
            found.append((path.relative_to(REPO_ROOT).as_posix(), node.name, wrapped))

    return found


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the .pylintrc rule                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_exemption_matches_request_user() -> None:
    """The decorator-injected argument is exempt."""
    assert _ignored_argument_pattern().match(EXEMPT_NAME)


@pytest.mark.parametrize('name', ['request_user_id', 'request_users', 'the_request_user', 'user'])
def test_the_exemption_matches_nothing_but_request_user(name: str) -> None:
    """The rule is anchored at both ends, so a lookalike name is still checked."""
    assert not _ignored_argument_pattern().match(name)


@pytest.mark.parametrize('name', ['_frame', 'ignored_value', 'unused_value'])
def test_the_default_exemptions_are_kept(name: str) -> None:
    """Adding the name did not replace the underscore / ignored_ / unused_ conventions."""
    assert _ignored_argument_pattern().match(name)


# -------------------------------------------------------------------------------------------------------------------- #
#                                         what keeps the name rule honest                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_scan_finds_the_known_unread_route() -> None:
    """A scan that finds nothing would pass the rule below for the wrong reason."""
    found = {(path, function) for path, function, _ in _unread_request_user_functions()}

    assert KNOWN_UNREAD_ROUTE in found


def test_an_unread_request_user_is_only_legal_on_a_route_the_decorator_wraps() -> None:
    """
    The name exemption is safe only where the decorator forces the parameter on the function

    A function that takes a ``request_user`` it never reads, and is not wrapped by
    ``@insert_request_user``, has a genuinely unused argument: drop it, use it, or give it a leading
    underscore - the exemption must not hide it.
    """
    offenders = [f'{path}::{function}' for path, function, wrapped in _unread_request_user_functions() if not wrapped]

    assert not offenders, f'unread request_user outside an @insert_request_user route: {offenders}'
