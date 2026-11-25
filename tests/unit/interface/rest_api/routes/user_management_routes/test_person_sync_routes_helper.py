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
Unit tests for user_management_routes.person_sync_routes_helper

Pinned: the body's overrides are read and a user overridden twice is refused; the views and the counts; the persons
whose Type changes are relocated first - a blocked one refuses before anything is written; switching on runs the pass
BEFORE the settings are stored, switching off stores them FIRST - and switches the group sync off too;
a problem refuses before anything is written; a Type the pass cannot write into is a 400; a resync while off is a 400
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_sync.sync_engine import SyncContext, SyncResult
from cmdb.framework.person_sync.sync_relocation_rules import PersonRelocation
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_routes_helper import (
    group_sync_view,
    pass_counts,
    resync,
    store_group_sync,
    store_user_sync,
    user_sync_from_body,
    user_sync_view,
)
from cmdb.interface.rest_api.routes.user_management_routes import person_sync_routes_helper as helper_module
from cmdb.errors.person_sync import PersonSyncTargetError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.interface.rest_api.routes.user_management_routes.person_sync_routes_helper'
TYPE_ID: int = 7
OTHER_TYPE_ID: int = 8
GROUP_TYPE_ID: int = 9
USER_ID: int = 5
OTHER_USER_ID: int = 6
PROBLEM: str = 'Type 7 is deactivated'
CALLER: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True)
ON_BODY: dict[str, Any] = {'active': True, 'default_type_id': TYPE_ID, 'on_blocked': 'cancel',
                           'type_overrides': [{'user_id': USER_ID, 'type_id': OTHER_TYPE_ID}]}
BOTH_ON: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=TYPE_ID),
                                                 groups=GroupSyncSettings(active=True, default_type_id=GROUP_TYPE_ID))


def _context(settings: PersonSyncSettings) -> SyncContext:
    """Mocked managers on the stored settings"""
    return SyncContext(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, CALLER)


class TestBodyAndViews:
    """Reading the body, answering the settings."""

    def test_the_overrides_are_read_by_user(self) -> None:
        """user id -> Type id"""
        assert user_sync_from_body(ON_BODY) == UserSyncSettings(active=True, default_type_id=TYPE_ID,
                                                                type_overrides={USER_ID: OTHER_TYPE_ID})

    def test_a_user_overridden_twice_is_refused(self) -> None:
        """400 naming the users"""
        body: dict[str, Any] = {**ON_BODY, 'type_overrides': [
            {'user_id': OTHER_USER_ID, 'type_id': TYPE_ID}, {'user_id': USER_ID, 'type_id': TYPE_ID},
            {'user_id': OTHER_USER_ID, 'type_id': OTHER_TYPE_ID},
        ]}

        with pytest.raises(BadRequest) as raised:
            user_sync_from_body(body)

        assert f'[{OTHER_USER_ID}]' in raised.value.description

    def test_the_views(self) -> None:
        """The stored shape; the group switch with the mappings"""
        mappings: list[dict[str, int]] = [{'user_group_id': 3, 'person_group_id': 4}]

        assert user_sync_view(BOTH_ON) == {'active': True, 'default_type_id': TYPE_ID, 'type_overrides': []}
        assert group_sync_view(BOTH_ON, mappings) == {'active': True, 'default_type_id': GROUP_TYPE_ID,
                                                      'mappings': mappings}

    def test_the_counts(self) -> None:
        """Created and edited counted; who left a mapped group named, in group order"""
        result = SyncResult(created=[1, 2], edits={3: MagicMock()}, left_members={8: [5, 6], 7: [4]})

        assert pass_counts(result) == {'created': 2, 'edited': 1, 'left': [
            {'person_group_id': 7, 'person_ids': [4]}, {'person_group_id': 8, 'person_ids': [5, 6]}]}


@pytest.fixture(name='wired')
def fixture_wired() -> Any:
    """The helper's collaborators patched; the calls recorded in order on one parent"""
    order = MagicMock()
    patches: dict[str, Any] = {
        'person_sync_context': MagicMock(return_value=_context(BOTH_ON)),
        'find_sync_settings_problems': MagicMock(return_value=[]),
        'plan_relocations': MagicMock(return_value=[]),
        'relocation_stores': MagicMock(),
        'apply_relocations': MagicMock(return_value=SyncResult()),
        'run_sync_pass': MagicMock(return_value=SyncResult(created=[9])),
        'switch_off_pass': MagicMock(return_value=SyncResult()),
        'write_sync_settings': MagicMock(),
        'emit_sync_events': MagicMock(),
        'build_sync_events': MagicMock(),
        'ManagerProvider': MagicMock(),
    }

    for name in ('apply_relocations', 'run_sync_pass', 'switch_off_pass', 'write_sync_settings'):
        order.attach_mock(patches[name], name)

    with patch.multiple(MODULE, **patches):
        yield order, patches


class TestStoreUserSync:
    """PUT /person_sync/users."""

    def test_switching_on_runs_the_pass_before_storing(self, wired: Any) -> None:
        """The pass sees the new settings; a failed pass leaves the stored ones"""
        order, patches = wired

        settings, result, _ = store_user_sync(CALLER, ON_BODY)

        assert settings.users.type_overrides == {USER_ID: OTHER_TYPE_ID}
        assert result.created == [9]
        assert [name for name, _, _ in order.mock_calls] == ['apply_relocations', 'run_sync_pass',
                                                             'write_sync_settings']
        assert patches['run_sync_pass'].call_args.args[0].settings == settings
        assert patches['apply_relocations'].call_args.args[1].settings == settings
        patches['emit_sync_events'].assert_called_once()

    def test_switching_off_stores_first_and_switches_the_group_sync_off(self, wired: Any) -> None:
        """The hooks stop before the persons are deactivated"""
        order, patches = wired

        settings, _, _ = store_user_sync(CALLER, {**ON_BODY, 'active': False})

        assert (settings.users.active, settings.groups.active) == (False, False)
        assert [name for name, _, _ in order.mock_calls] == ['apply_relocations', 'write_sync_settings',
                                                             'switch_off_pass']
        patches['run_sync_pass'].assert_not_called()

    def test_a_problem_refuses_before_anything_is_written(self, wired: Any) -> None:
        """The rules' problems in one 400; nothing planned"""
        order, patches = wired
        patches['find_sync_settings_problems'].return_value = [PROBLEM]

        with pytest.raises(BadRequest) as raised:
            store_user_sync(CALLER, ON_BODY)

        assert raised.value.description == PROBLEM
        assert order.mock_calls == []
        patches['plan_relocations'].assert_not_called()

    def test_a_blocked_person_refuses_before_anything_is_written(self, wired: Any) -> None:
        """The relocations planned on the new settings; cancel refuses"""
        order, patches = wired
        patches['plan_relocations'].return_value = [PersonRelocation(USER_ID, 50, TYPE_ID, OTHER_TYPE_ID, ('x',))]

        with pytest.raises(BadRequest):
            store_user_sync(CALLER, ON_BODY)

        assert order.mock_calls == []
        assert patches['plan_relocations'].call_args.args[2].type_overrides == {USER_ID: OTHER_TYPE_ID}

    def test_the_counts_merge_the_relocation_and_the_pass(self, wired: Any) -> None:
        """Both results answered"""
        _, patches = wired
        patches['apply_relocations'].return_value = SyncResult(created=[3])

        _, result, _ = store_user_sync(CALLER, ON_BODY)

        assert result.created == [3, 9]

    def test_an_unusable_person_type_is_a_400_with_nothing_stored(self, wired: Any) -> None:
        """The pass refuses before it writes"""
        _, patches = wired
        patches['run_sync_pass'].side_effect = PersonSyncTargetError(PROBLEM)

        with pytest.raises(BadRequest):
            store_user_sync(CALLER, ON_BODY)

        patches['write_sync_settings'].assert_not_called()


class TestStoreGroupSync:
    """PUT /person_sync/groups."""

    def test_switching_on_runs_the_pass(self, wired: Any) -> None:
        """Then stores - the switch and the default together"""
        order, _ = wired

        settings, _ = store_group_sync(CALLER, True, OTHER_TYPE_ID)

        assert (settings.groups.active, settings.groups.default_type_id) == (True, OTHER_TYPE_ID)
        assert [name for name, _, _ in order.mock_calls] == ['run_sync_pass', 'write_sync_settings']

    def test_switching_off_only_stores(self, wired: Any) -> None:
        """The groups are unlocked, kept as they are"""
        order, _ = wired

        settings, result = store_group_sync(CALLER, False, GROUP_TYPE_ID)

        assert (settings.users.active, settings.groups.active, settings.groups.default_type_id) == (
            True, False, GROUP_TYPE_ID)
        assert result == SyncResult()
        assert order.mock_calls == [call.write_sync_settings(order.mock_calls[0].args[0], settings)]


class TestResync:
    """POST /person_sync/resync."""

    def test_while_off_it_is_refused(self, wired: Any) -> None:
        """400, no pass"""
        _, patches = wired
        patches['person_sync_context'].return_value = _context(PersonSyncSettings())

        with pytest.raises(BadRequest):
            resync(CALLER)

        patches['run_sync_pass'].assert_not_called()

    def test_while_on_it_runs_the_pass_on_the_stored_settings(self, wired: Any) -> None:
        """Nothing stored; the settings it ran on come back with the result"""
        _, patches = wired
        stored: PersonSyncSettings = patches['person_sync_context'].return_value.settings

        settings, result = resync(CALLER)

        assert (settings, result.created) == (stored, [9])
        patches['write_sync_settings'].assert_not_called()


class TestTheMappingAcl:
    """The caller is judged on the Type it chose - the sync writes as the system."""

    @pytest.mark.parametrize('denied, refused', [
        ({'READ'}, True), ({'UPDATE'}, True), (set(), False),
    ], ids=['no-read', 'no-update', 'allowed'])
    def test_every_permission_is_needed(self, denied: set[str], refused: bool) -> None:
        """READ and UPDATE on an existing group's Type"""
        def _denied(_user: Any, permission: Any) -> list[int]:
            return [7] if permission.name in denied else []

        with Flask(__name__).app_context(), \
                patch.object(helper_module, 'resolve_denied_type_ids', side_effect=_denied):
            if refused:
                with pytest.raises(HTTPException) as caught:
                    helper_module._abort_unless_permitted(  # pylint: disable=protected-access
                        CALLER, 7, helper_module.MAPPED_GROUP_PERMISSIONS, 'denied')

                assert caught.value.code == HTTPStatus.FORBIDDEN
            else:
                helper_module._abort_unless_permitted(  # pylint: disable=protected-access
                    CALLER, 7, helper_module.MAPPED_GROUP_PERMISSIONS, 'denied')
