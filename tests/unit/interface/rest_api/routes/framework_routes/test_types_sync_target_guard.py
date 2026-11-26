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
Unit tests of the user sync's Type guards in types_change_guard_helper

Pinned: only a Type carrying PERSON or PERSON_GROUP has the settings read - any other update costs nothing; the user
group sync's default is judged by the person group rule; a target's unusable
update is reported by the blocker and aborted 400 by the guard; the PUT route's change guard and the type import's
stored-type blocker both ask it
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_update_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_change_guard_helper import (
    guard_sync_target_change,
    sync_target_change_blocker,
)
from cmdb.interface.rest_api.routes.importer_routes import importer_type_rules
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_change_guard_helper'
TARGET_TYPE_ID: int = 61
GROUP_TYPE_ID: int = 62
TARGETING: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(default_type_id=TARGET_TYPE_ID))
USER: Any = SimpleNamespace(public_id=1)


def _deactivated_target() -> CmdbType:
    """The target Type, deactivated by the update"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, 'target', TARGET_TYPE_ID)
    document['active'] = False

    return CmdbType.from_data(document)


def test_a_type_without_a_person_marker_reads_no_settings() -> None:
    """Only a PERSON or PERSON_GROUP Type can be guarded"""
    other = SimpleNamespace(special_type=None, public_id=TARGET_TYPE_ID)

    with patch(f'{PATH}.ManagerProvider') as provider:
        assert sync_target_change_blocker(USER, other) is None

    provider.get_manager.assert_not_called()


def _deactivated_group_type() -> CmdbType:
    """A PERSON_GROUP Type, deactivated by the update"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON_GROUP, 'groups', GROUP_TYPE_ID)
    document['active'] = False

    return CmdbType.from_data(document)


@pytest.mark.parametrize('default_type_id, refused', [(GROUP_TYPE_ID, True), (TARGET_TYPE_ID, False)],
                         ids=['the-default', 'another-group-type'])
def test_the_group_defaults_unusable_update_is_reported(default_type_id: int, refused: bool) -> None:
    """Only the group sync's default is judged - by the person group rule; no linked person is read"""
    settings = PersonSyncSettings(groups=GroupSyncSettings(default_type_id=default_type_id))

    with patch(f'{PATH}.ManagerProvider') as provider, patch(f'{PATH}.read_sync_settings', return_value=settings):
        reason = sync_target_change_blocker(USER, _deactivated_group_type())

    assert (reason is not None, provider.get_manager.call_count) == (refused, 1)
    if refused:
        assert reason.startswith(f"Type {GROUP_TYPE_ID} is the user group sync's default Type")


def test_a_targets_unusable_update_is_reported_and_aborted() -> None:
    """The blocker answers it, the guard aborts 400 with it"""
    with patch(f'{PATH}.ManagerProvider'), patch(f'{PATH}.read_sync_settings', return_value=TARGETING):
        reason = sync_target_change_blocker(USER, _deactivated_target())

        with pytest.raises(HTTPException) as raised:
            guard_sync_target_change(USER, _deactivated_target())

    assert reason and str(TARGET_TYPE_ID) in reason
    assert raised.value.code == 400
    assert raised.value.description == reason


def test_the_put_route_asks_the_guard() -> None:
    """Last of the change guards"""
    old_type, new_type, sync_guard = MagicMock(special_type=None), MagicMock(), MagicMock()

    with patch.multiple(types_update_helper, guard_field_identifier_change=MagicMock(),
                        guard_mds_section_identifier_change=MagicMock(), guard_location_field_removal=MagicMock(),
                        guard_referenced_section_removal=MagicMock(), guard_selectable_as_parent_change=MagicMock(),
                        guard_uses_ports_change=MagicMock(), guard_person_selector_narrowing=MagicMock(),
                        guard_sync_target_change=sync_guard, guard_scope_field_change=MagicMock(),
                        guard_rule_field_change=MagicMock()):
        types_update_helper.guard_type_update_changes(USER, old_type, new_type, None)

    sync_guard.assert_called_once_with(USER, new_type)


def test_the_type_import_asks_the_blocker() -> None:
    """The import refuses the entry with the same wording"""
    old_type = CmdbType.from_data(build_default_person_type(SpecialType.PERSON, 'target', TARGET_TYPE_ID))

    with patch.object(importer_type_rules, 'sync_target_change_blocker', return_value='refused') as blocker:
        assert importer_type_rules.stored_type_update_blocker(USER, old_type, _deactivated_target(), False) == (
            'refused')

    blocker.assert_called_once()
