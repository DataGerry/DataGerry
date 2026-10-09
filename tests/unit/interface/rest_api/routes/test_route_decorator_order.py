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
A census of every REST route: the caller is authenticated and authorized before its input is read

Decorators run top-down, so a parser or validator listed above ``insert_request_user``,
``verify_api_access`` or ``protect`` reads the request of a caller nobody has identified yet: a stranger
sending a malformed ``filter`` is answered with the parser's own error text (400) instead of the 401 every
other route gives, and a user without the right learns how the route parses before being refused.

The authentication decorators keep their own order too: ``insert_request_user`` before ``verify_api_access``
before every ``protect`` - the level and the right are checks ON the injected user.

Read with ``ast`` rather than by importing the routes, so the census covers every route file whether or
not a test imports it. A route that needs an exception has to be listed here with its reason
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

ROUTES_ROOT: Path = Path(__file__).resolve().parents[5] / 'cmdb' / 'interface' / 'rest_api' / 'routes'

ROUTE_DECORATOR: str = 'route'
AUTH_DECORATORS: frozenset[str] = frozenset({'insert_request_user', 'verify_api_access', 'protect'})
VALIDATOR_DECORATOR: str = 'validate'
PARSER_PREFIX: str = 'parse'

# (route file relative to ROUTES_ROOT, function name) -> why its input may be read before authentication
EXEMPT: dict[tuple[str, str], str] = {}


def _decorator_name(decorator: ast.expr) -> str:
    """The attribute or bare name a decorator is called by: `bp.protect(...)` -> 'protect'."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator

    if isinstance(target, ast.Attribute):
        return target.attr

    return target.id if isinstance(target, ast.Name) else ''


def _is_input_reader(name: str) -> bool:
    """A decorator that reads the request's parameters or body."""
    return name == VALIDATOR_DECORATOR or name.startswith(PARSER_PREFIX)


def _routes() -> list[tuple[str, str, list[str]]]:
    """Every route function: (file, function name, decorator names top-down)."""
    found: list[tuple[str, str, list[str]]] = []

    for path in sorted(ROUTES_ROOT.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [_decorator_name(decorator) for decorator in node.decorator_list]

                if ROUTE_DECORATOR in names:
                    found.append((str(path.relative_to(ROUTES_ROOT)), node.name, names))

    return found


ROUTES: list[tuple[str, str, list[str]]] = _routes()


def test_the_census_finds_the_routes() -> None:
    """Guards the census itself: a moved routes folder must not make every check vacuous"""
    assert len(ROUTES) > 300
    assert any(_is_input_reader(name) for _, _, names in ROUTES for name in names)


@pytest.mark.parametrize('route_file, function, names', ROUTES, ids=[f'{r[0]}::{r[1]}' for r in ROUTES])
def test_no_input_is_read_before_the_caller_is_authenticated(route_file: str, function: str,
                                                            names: list[str]) -> None:
    """Every parser and validator sits below every authentication and authorization decorator"""
    if (route_file, function) in EXEMPT:
        pytest.skip(EXEMPT[(route_file, function)])

    auth_positions = [index for index, name in enumerate(names) if name in AUTH_DECORATORS]
    reader_positions = [index for index, name in enumerate(names) if _is_input_reader(name)]

    if not auth_positions or not reader_positions:
        return

    assert min(reader_positions) > max(auth_positions), (
        f'{route_file}::{function} reads its input before authenticating: {names}'
    )


AUTH_ORDER: tuple[str, ...] = ('insert_request_user', 'verify_api_access', 'protect')


@pytest.mark.parametrize('route_file, function, names', ROUTES, ids=[f'{r[0]}::{r[1]}' for r in ROUTES])
def test_the_authentication_decorators_keep_their_order(route_file: str, function: str, names: list[str]) -> None:
    """insert_request_user, then verify_api_access, then every protect - whichever of them a route carries"""
    ranks: list[int] = [AUTH_ORDER.index(name) for name in names if name in AUTH_ORDER]

    assert ranks == sorted(ranks), f'{route_file}::{function} orders its authentication decorators {names}'


def test_every_exemption_still_names_a_route() -> None:
    """A stale exemption would silently cover a route added later under the same name"""
    known = {(route_file, function) for route_file, function, _ in ROUTES}

    assert set(EXEMPT) <= known
