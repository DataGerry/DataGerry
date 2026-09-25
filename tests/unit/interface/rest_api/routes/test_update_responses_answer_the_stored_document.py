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
No update route answers with the request body it was handed

An update response has to be the document as stored. The request body is not that document: a key it
leaves out - or sends as ``null`` - is stored as the model's empty value, and whether the body
happens to carry that value afterwards depends on whether the model's ``normalize_document`` fills it
in place, which most do not. So an ``UpdateSingleResponse`` built from one of the route function's own
parameters (the validated body arrives as one) is refused here; the route answers what it wrote -
``routes_helper.update_item_from_payload``, the serialised model, or a read-back.

Import-free: the route modules are parsed with ``ast``
"""
import ast
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[5]
ROUTES_ROOT: Path = REPO_ROOT / 'cmdb' / 'interface' / 'rest_api' / 'routes'

RESPONSE_CLASS: str = 'UpdateSingleResponse'
RESULT_KEYWORD: str = 'result'


def _parameter_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every parameter name of a function."""
    arguments = function.args

    return {argument.arg for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]}


def _answered_names(call: ast.Call) -> list[str]:
    """The bare names an UpdateSingleResponse call is built from (its result, positional or keyword)."""
    candidates: list[ast.expr] = call.args[:1] + [kw.value for kw in call.keywords if kw.arg == RESULT_KEYWORD]

    return [candidate.id for candidate in candidates if isinstance(candidate, ast.Name)]


def _updates_answering_a_parameter() -> list[str]:
    """path::function for every UpdateSingleResponse built from a parameter of its own route function."""
    offenders: list[str] = []

    for path in sorted(ROUTES_ROOT.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))

        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            parameters: set[str] = _parameter_names(function)

            for node in ast.walk(function):
                is_response = isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == RESPONSE_CLASS

                if is_response and parameters.intersection(_answered_names(node)):
                    offenders.append(f'{path.relative_to(REPO_ROOT).as_posix()}::{function.name}')

    return offenders


def test_the_scan_sees_the_update_responses() -> None:
    """A scan that parses nothing would pass the rule below for the wrong reason."""
    sources = [path.read_text(encoding='utf-8') for path in ROUTES_ROOT.rglob('*.py')]

    assert sum(source.count(f'{RESPONSE_CLASS}(') for source in sources) > 20


def test_the_scan_catches_a_route_that_echoes_its_body(tmp_path: Path) -> None:
    """The detector itself: a route answering its `data` parameter is found."""
    route = tmp_path / 'echo_route.py'
    route.write_text('def update(public_id, data):\n    return UpdateSingleResponse(data).make_response()\n')
    function = ast.parse(route.read_text()).body[0]
    call = next(node for node in ast.walk(function) if isinstance(node, ast.Call) and _answered_names(node))

    assert _parameter_names(function).intersection(_answered_names(call)) == {'data'}


def test_no_update_route_answers_its_request_body() -> None:
    """Every update route answers the document it stored."""
    offenders = _updates_answering_a_parameter()

    assert not offenders, f'update routes answering their own request body: {offenders}'
