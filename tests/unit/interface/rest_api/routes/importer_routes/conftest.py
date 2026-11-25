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
Shared fixtures for the importer-route unit tests
"""
import pytest

from tests.utils.type_acl_engine_stub import decide_by_type_acls
from tests.utils.type_import_builders import HELPER
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(name='side_effect_calls', autouse=True)
def fixture_stub_side_effects(monkeypatch) -> dict[str, list]:
    """
    Stubs the persistence side effects the per-entry type-import steps end in

    They reach real managers through the ManagerProvider (and therefore an application context),
    which a unit test has no business setting up - the functions themselves are covered directly in
    test_importer_type_helper. The recorded calls let a test assert that the step invoked them.
    """
    calls: dict[str, list] = {'create': [], 'update': []}

    monkeypatch.setattr(
        f'{HELPER}.apply_import_create_side_effects', lambda *args: calls['create'].append(args),
    )
    monkeypatch.setattr(
        f'{HELPER}.apply_import_update_side_effects', lambda *args: calls['update'].append(args),
    )

    return calls


@pytest.fixture(name='no_type_restricted', autouse=True)
def fixture_no_type_restricted(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Lets the access engine answer from no Type ACL - every Type unrestricted, no database read

    The import steps judge the stored Type (and the importer's rights on it) through the access engine, which reads
    the stored grants through the ManagerProvider. A test judging a Type's ACL registers the Types it judges
    (``decide_by_type_acls``), which replaces this
    """
    decide_by_type_acls(monkeypatch, [])
