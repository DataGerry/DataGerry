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
Tripwire: every ISMS route answers its errors through the two route error decorators

``handle_route_errors`` owns the generic 500, ``handle_manager_errors`` the route's manager-error 400s.
A hand-written ``except Exception`` tail swallows the aborts raised inside it (a 400 becomes a 500), and
a hand-written ``except XxxManagerError`` arm is the copy-paste the decorator table replaced - so a route
may contain neither.

The manager-error tables are checked against the rule they encode: an error class answers with the
template of its operation (an ``UpdateError`` never with ``DELETE``), a ``RiskUsageError`` is a refusal,
and every class and label in a file belong to that file's entity - the copy-paste slip a table built
from a sibling file would carry.

Read with ``ast``, so every route file is covered whether or not a test imports it.
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

ISMS_ROUTES_ROOT: Path = (
    Path(__file__).resolve().parents[6] / 'cmdb' / 'interface' / 'rest_api' / 'routes' / 'isms_routes'
)

ROUTE_DECORATOR: str = 'route'
ROUTE_ERRORS_DECORATOR: str = 'handle_route_errors'
MANAGER_ERRORS_DECORATOR: str = 'handle_manager_errors'
REFUSALS_KEYWORD: str = 'refusals'
TABLE_BUILDER: str = 'manager_error_messages'
TEMPLATE_ENUM: str = 'IsmsManagerErrorMessage'
GENERIC_EXCEPTION: str = 'Exception'
MANAGER_ERROR_MARKER: str = 'Manager'
MANAGER_ERROR_SUFFIX: str = 'Error'

# A route file -> the label constant its tables use, i.e. the entity the file serves
FILE_LABELS: dict[str, str] = {
    'control_measure_routes.py': 'CONTROL_MEASURE_LABEL',
    'impact_category_routes.py': 'IMPACT_CATEGORY_LABEL',
    'impact_routes.py': 'IMPACT_LABEL',
    'likelihood_routes.py': 'LIKELIHOOD_LABEL',
    'measure_control_assignment_routes.py': 'CONTROL_MEASURE_ASSIGNMENT_LABEL',
    'protection_goal_routes.py': 'PROTECTION_GOAL_LABEL',
    'risk_assessment_routes.py': 'RISK_ASSESSMENT_LABEL',
    'risk_class_routes.py': 'RISK_CLASS_LABEL',
    'risk_matrix_routes.py': 'RISK_MATRIX_LABEL',
    'risk_routes.py': 'RISK_LABEL',
    'threat_routes.py': 'THREAT_LABEL',
    'vulnerability_routes.py': 'VULNERABILITY_LABEL',
}

# A label constant -> the prefix of its manager's error classes
LABEL_ERROR_PREFIXES: dict[str, str] = {
    'CONTROL_MEASURE_LABEL': 'ControlMeasureManager',
    'IMPACT_CATEGORY_LABEL': 'ImpactCategoryManager',
    'IMPACT_LABEL': 'ImpactManager',
    'LIKELIHOOD_LABEL': 'LikelihoodManager',
    'CONTROL_MEASURE_ASSIGNMENT_LABEL': 'ControlMeasureAssignmentManager',
    'PROTECTION_GOAL_LABEL': 'ProtectionGoalManager',
    'RISK_ASSESSMENT_LABEL': 'RiskAssessmentManager',
    'RISK_CLASS_LABEL': 'RiskClassManager',
    'RISK_MATRIX_LABEL': 'RiskMatrixManager',
    'RISK_LABEL': 'RiskManager',
    'THREAT_LABEL': 'ThreatManager',
    'VULNERABILITY_LABEL': 'VulnerabilityManager',
}

# An error class's operation (the suffix after its manager prefix) -> the templates it may answer with
OPERATION_TEMPLATES: dict[str, frozenset[str]] = {
    'InsertError': frozenset({'INSERT', 'INSERT_DUPLICATE'}),
    'GetError': frozenset({'GET', 'GET_CREATED', 'BULK_USAGE'}),
    'IterationError': frozenset({'ITERATE'}),
    'UpdateError': frozenset({'UPDATE'}),
    'DeleteError': frozenset({'DELETE', 'BULK_DELETE'}),
    'RiskUsageError': frozenset({'USED_BY_RISKS'}),
}

# Operations that are business-rule refusals, listed under `refusals=` and nowhere else
REFUSAL_OPERATIONS: frozenset[str] = frozenset({'RiskUsageError'})


def _decorator_name(decorator: ast.expr) -> str:
    """The attribute or bare name a decorator is called by: `bp.route(...)` -> 'route'."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    return target.id if isinstance(target, ast.Name) else ''


def _routes() -> list[tuple[str, ast.FunctionDef]]:
    """Every ISMS route function: (file name, function node)."""
    found: list[tuple[str, ast.FunctionDef]] = []

    for path in sorted(ISMS_ROUTES_ROOT.glob('*.py')):
        for node in ast.parse(path.read_text(encoding='utf-8')).body:
            if isinstance(node, ast.FunctionDef):
                if ROUTE_DECORATOR in [_decorator_name(decorator) for decorator in node.decorator_list]:
                    found.append((path.name, node))

    return found


def _manager_tables(node: ast.FunctionDef) -> list[tuple[bool, ast.Call]]:
    """A route's `manager_error_messages(...)` calls: (is it the refusals table, the call)."""
    tables: list[tuple[bool, ast.Call]] = []

    for decorator in node.decorator_list:
        if _decorator_name(decorator) != MANAGER_ERRORS_DECORATOR:
            continue

        arguments = [(False, argument) for argument in decorator.args]
        arguments += [(keyword.arg == REFUSALS_KEYWORD, keyword.value) for keyword in decorator.keywords]

        for is_refusal, argument in arguments:
            if isinstance(argument, ast.Call) and _decorator_name(argument) == TABLE_BUILDER:
                tables.append((is_refusal, argument))

    return tables


def _handled_names(handler: ast.ExceptHandler) -> list[str]:
    """The class names an `except` clause catches."""
    if handler.type is None:
        return [GENERIC_EXCEPTION]

    caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]

    return [ast.unparse(error_class).split('.')[-1] for error_class in caught]


ROUTES: list[tuple[str, ast.FunctionDef]] = _routes()
ROUTE_IDS: list[str] = [f'{file}::{node.name}' for file, node in ROUTES]
TABLE_ROUTES: list[tuple[str, ast.FunctionDef]] = [
    (file, node) for file, node in ROUTES if file in FILE_LABELS and _manager_tables(node)
]


def test_the_census_finds_the_routes() -> None:
    """Guards the census itself: a moved folder must not make every check vacuous."""
    assert len(ROUTES) > 60
    assert len(TABLE_ROUTES) > 50
    assert set(FILE_LABELS) <= {file for file, _ in ROUTES}


@pytest.mark.parametrize('route_file, node', ROUTES, ids=ROUTE_IDS)
def test_every_route_carries_the_generic_tail(route_file: str, node: ast.FunctionDef) -> None:
    """handle_route_errors owns the 500, so no route writes its own."""
    names = [_decorator_name(decorator) for decorator in node.decorator_list]

    assert ROUTE_ERRORS_DECORATOR in names, f'{route_file}::{node.name} has no @{ROUTE_ERRORS_DECORATOR}'


@pytest.mark.parametrize('route_file, node', ROUTES, ids=ROUTE_IDS)
def test_the_manager_table_sits_directly_below_the_tail(route_file: str, node: ast.FunctionDef) -> None:
    """Its 400s are HTTPExceptions the tail hands through - only when the tail wraps it."""
    names = [_decorator_name(decorator) for decorator in node.decorator_list]

    if MANAGER_ERRORS_DECORATOR not in names:
        return

    assert names[-2:] == [ROUTE_ERRORS_DECORATOR, MANAGER_ERRORS_DECORATOR], f'{route_file}::{node.name}: {names}'


@pytest.mark.parametrize('route_file, node', ROUTES, ids=ROUTE_IDS)
def test_no_route_hand_writes_an_error_arm(route_file: str, node: ast.FunctionDef) -> None:
    """Neither the generic tail nor a manager-error arm: both belong to the decorators."""
    offending = [
        name
        for handler in ast.walk(node) if isinstance(handler, ast.ExceptHandler)
        for name in _handled_names(handler)
        if name == GENERIC_EXCEPTION or (MANAGER_ERROR_MARKER in name and name.endswith(MANAGER_ERROR_SUFFIX))
    ]

    assert not offending, f'{route_file}::{node.name} catches {offending} by hand'


@pytest.mark.parametrize('route_file, node', TABLE_ROUTES, ids=[f'{f}::{n.name}' for f, n in TABLE_ROUTES])
def test_every_table_entry_follows_its_operation(route_file: str, node: ast.FunctionDef) -> None:
    """The file's own entity, the operation's own template, and refusals only under `refusals=`."""
    expected_label = FILE_LABELS[route_file]
    error_prefix = LABEL_ERROR_PREFIXES[expected_label]

    for is_refusal, table in _manager_tables(node):
        label, entries = table.args

        assert ast.unparse(label) == expected_label, f'{node.name} uses {ast.unparse(label)}'
        assert isinstance(entries, ast.Dict), f'{node.name}: the table must be a literal dict'

        for error_class, template in zip(entries.keys, entries.values):
            class_name = ast.unparse(error_class)
            operation = class_name.removeprefix(error_prefix)

            assert class_name.startswith(error_prefix), f'{node.name}: {class_name} is not a {error_prefix} error'
            assert operation in OPERATION_TEMPLATES, f'{node.name}: unknown operation of {class_name}'
            assert ast.unparse(template).startswith(f'{TEMPLATE_ENUM}.'), f'{node.name}: {class_name}'
            assert template.attr in OPERATION_TEMPLATES[operation], (
                f'{node.name}: {class_name} answers {template.attr}'
            )
            assert (operation in REFUSAL_OPERATIONS) == is_refusal, (
                f'{node.name}: {class_name} is listed as a {"refusal" if is_refusal else "failure"}'
            )
