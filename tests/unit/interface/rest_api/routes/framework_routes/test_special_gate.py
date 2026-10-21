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
Unit tests for what decides whether the DataGerry Assistant may run

  - ``read_profile_selection``: known profiles only, each once, in order; none or an unknown one is a 400
  - ``holds_assistant_rights``: both type.add and category.add; ``assistant_has_run``: the marker section exists
  - ``SettingsManager.claim_section``: one insert, a duplicate is "already claimed", anything else raises
  - ``POST /special/profiles`` stacks one ``.protect`` per right below the authentication; ``/intro`` carries none
"""
import ast
import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.manager import SettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes import special_helper, special_routes
from cmdb.interface.rest_api.routes.framework_routes.special_constants import (
    ASSISTANT_RIGHTS,
    ASSISTANT_SETTINGS_SECTION,
    NO_PROFILES_MESSAGE,
    UNKNOWN_PROFILES_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.special_helper import (
    assistant_has_run,
    holds_assistant_rights,
    read_profile_selection,
)
from cmdb.errors.database import DocumentInsertDuplicateKeyError, DocumentInsertError
# -------------------------------------------------------------------------------------------------------------------- #

RACK: str = ProfileName.RACK.value
IPAM: str = ProfileName.IPAM.value
USER: CmdbUser = CmdbUser(public_id=5, user_name='caller', active=True, group_id=9)

# -------------------------------------------------- the selection --------------------------------------------------- #

class TestReadProfileSelection:
    """The '#'-joined ProfileName values"""

    def test_known_profiles_are_answered_once_in_order(self) -> None:
        """A repeated name is seeded once"""
        assert read_profile_selection({'data': f'{IPAM}#{RACK}#{IPAM}'}) == [IPAM, RACK]

    @pytest.mark.parametrize('params', [{}, {'data': ''}, {'data': '#'}, {'data': 5}],
                             ids=['missing', 'empty', 'separator-only', 'not-text'])
    def test_no_profile_is_a_400(self, params: dict[str, Any]) -> None:
        """Nothing to seed"""
        with pytest.raises(HTTPException) as exc_info:
            read_profile_selection(params)

        assert (exc_info.value.code, exc_info.value.description) == (400, NO_PROFILES_MESSAGE)

    def test_unknown_profiles_are_a_400_naming_them(self) -> None:
        """A typo no longer drops a profile silently"""
        with pytest.raises(HTTPException) as exc_info:
            read_profile_selection({'data': f'{RACK}#SERVER#rack'})

        assert (exc_info.value.code, exc_info.value.description) == (
            400, UNKNOWN_PROFILES_MESSAGE.format(names='SERVER, rack'))

# ---------------------------------------------------- the checks ---------------------------------------------------- #

@pytest.mark.parametrize('held, expected', [
    (set(ASSISTANT_RIGHTS), True), ({ASSISTANT_RIGHTS[0]}, False), ({ASSISTANT_RIGHTS[1]}, False), (set(), False),
], ids=['both', 'type-only', 'category-only', 'none'])
def test_holds_assistant_rights_needs_both(held: set[str], expected: bool) -> None:
    """type.add and category.add"""
    with patch.object(special_helper, 'user_has_right', side_effect=lambda right, _user: right in held):
        assert holds_assistant_rights(USER) is expected


@pytest.mark.parametrize('section, expected', [(None, False), ({'claimed_by': 1}, True)], ids=['never', 'ran'])
def test_assistant_has_run_reads_the_marker(section: Any, expected: bool) -> None:
    """The marker section is what records a run"""
    settings_manager = MagicMock()
    settings_manager.get_section.return_value = section

    assert assistant_has_run(settings_manager) is expected
    settings_manager.get_section.assert_called_once_with(ASSISTANT_SETTINGS_SECTION)

# ---------------------------------------------------- the claim ----------------------------------------------------- #

def _settings_manager(insert_error: Exception | None = None) -> SettingsManager:
    """A SettingsManager on a stubbed database manager"""
    manager = SettingsManager.__new__(SettingsManager)
    manager.dbm = MagicMock()
    manager.db_name = 'cmdb-unit'

    if insert_error is not None:
        manager.dbm.insert.side_effect = insert_error

    return manager


class TestClaimSection:
    """An atomic insert-if-absent on the section's _id"""

    def test_a_new_section_is_claimed(self) -> None:
        """One insert, its _id the section, no public_id drawn"""
        manager = _settings_manager()

        assert manager.claim_section('marker', {'claimed_by': 5}) is True
        manager.dbm.insert.assert_called_once_with(SettingsManager.COLLECTION, 'cmdb-unit',
                                                   {'claimed_by': 5, '_id': 'marker'}, skip_public=True)

    def test_an_existing_section_is_not_claimed(self) -> None:
        """The unique _id refused the insert"""
        assert _settings_manager(DocumentInsertDuplicateKeyError('E11000')).claim_section('marker', {}) is False

    def test_any_other_failure_is_raised(self) -> None:
        """An outage is not 'already claimed'"""
        with pytest.raises(DocumentInsertError):
            _settings_manager(DocumentInsertError('down')).claim_section('marker', {})

    @pytest.mark.parametrize('deleted, expected', [(1, True), (0, False)])
    def test_delete_section_reports_whether_one_was_deleted(self, deleted: int, expected: bool) -> None:
        """By its _id"""
        manager = _settings_manager()
        manager.dbm.delete.return_value = MagicMock(deleted_count=deleted)

        assert manager.delete_section('marker') is expected
        manager.dbm.delete.assert_called_once_with(SettingsManager.COLLECTION, 'cmdb-unit', {'_id': 'marker'})

# ----------------------------------------------------- the gate ----------------------------------------------------- #

def _decorators(function_name: str) -> list[ast.expr]:
    """A route's decorators, outermost first"""
    tree = ast.parse(inspect.getsource(special_routes))

    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == function_name).decorator_list


def _name(decorator: ast.expr) -> str:
    """`bp.protect(...)` -> 'protect'"""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator

    return target.attr if isinstance(target, ast.Attribute) else getattr(target, 'id', '')


def test_the_profiles_route_stacks_both_rights() -> None:
    """One protect per right the run needs, in ASSISTANT_RIGHTS order"""
    rights = [ast.unparse(keyword.value) for decorator in _decorators('create_initial_profiles')
              if _name(decorator) == 'protect' for keyword in decorator.keywords if keyword.arg == 'right']

    assert rights == ['ASSISTANT_RIGHTS[0]', 'ASSISTANT_RIGHTS[1]']


def test_the_intro_route_carries_no_right() -> None:
    """Every user asks it after login - it answers false instead of refusing"""
    assert 'protect' not in [_name(decorator) for decorator in _decorators('show_datagerry_assistant')]
