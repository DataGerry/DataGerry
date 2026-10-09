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
Tripwire: a manager is never bound to ``request_user.database`` directly

Which database a request's work goes to is ``ManagerProvider.tenant_database(request_user)``: the user's tenant in
cloud mode, refused when it names none, and None - the configured database - on premise, whatever the user document
says. Reading ``request_user.database`` straight into a manager or connector constructor skips both halves: on premise
it bound the OpenCelium token cache to a database named after the model's old fallback (``'test'``), and in cloud mode
it would let a user without a database fall through to the process-wide one.

The scan flags a call whose name ends in ``Manager`` or ``Connector`` and that passes ``request_user.database`` as an
argument. Other reads of the field - a tenant prefix or a portal call inside a hosted-cloud branch - are not
constructors and are left alone. Read with ``ast``, so every module is covered whether or not a test imports it
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'

CONSTRUCTOR_SUFFIXES: tuple[str, ...] = ('Manager', 'Connector')
REQUEST_USER: str = 'request_user'
DATABASE_ATTRIBUTE: str = 'database'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000


def _call_name(node: ast.Call) -> str:
    """The called name: `Foo(...)` -> 'Foo', `mod.Foo(...)` -> 'Foo'."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ''


def _is_request_user_database(node: ast.expr) -> bool:
    """`request_user.database` and nothing else."""
    return (
        isinstance(node, ast.Attribute) and node.attr == DATABASE_ATTRIBUTE
        and isinstance(node.value, ast.Name) and node.value.id == REQUEST_USER
    )


def find_direct_bindings(source: str) -> list[int]:
    """
    The lines that construct a manager or connector from `request_user.database`

    Args:
        source (str): A module's source

    Returns:
        list[int]: Line numbers of the offending calls
    """
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and _call_name(node).endswith(CONSTRUCTOR_SUFFIXES)
        and any(_is_request_user_database(arg) for arg in [*node.args, *(kw.value for kw in node.keywords)])
    ]


def test_no_manager_is_bound_to_request_user_database() -> None:
    """Every manager and connector takes its database from ManagerProvider.tenant_database"""
    modules = sorted(CMDB_ROOT.rglob('*.py'))
    offenders = [
        f'{path.relative_to(CMDB_ROOT.parent)}:{line}'
        for path in modules
        for line in find_direct_bindings(path.read_text(encoding='utf-8'))
    ]

    assert len(modules) >= MIN_SCANNED_MODULES
    assert not offenders


@pytest.mark.parametrize('source, expected', [
    ('OcConnectorManager(current_app.database_manager, request_user.database)', [1]),
    ('m.OcSchedulerManager(dbm, db_name=request_user.database)', [1]),
    ('OcApiConnector(dbm, request_user.database)', [1]),
    ('OcConnectorManager(dbm, ManagerProvider.tenant_database(request_user))', []),
    ('map_oc_name(request_user.database, title)', []),
    ('dg_sp_manager.save_connector_id(1, request_user.email, request_user.database)', []),
], ids=['positional', 'keyword', 'connector', 'resolver', 'prefix', 'portal-call'])
def test_the_scan_tells_a_binding_from_other_reads(source: str, expected: list[int]) -> None:
    """The detector itself: constructors are flagged, the resolver and non-constructor reads are not"""
    assert find_direct_bindings(source) == expected
