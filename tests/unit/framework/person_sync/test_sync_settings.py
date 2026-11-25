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
Unit tests for cmdb.framework.person_sync.sync_settings

Pinned: a missing section or key reads as off and unchosen; the stored shape (overrides as a list of entries in user
id order) and its round trip; the targets are the default plus every override; the read and the write address the one
section; switching the user sync off switches the group sync off and keeps the targets
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION
from cmdb.framework.person_sync.sync_settings import (
    GroupSyncSettings,
    PersonSyncSettings,
    UserSyncSettings,
    read_sync_settings,
    settings_from_document,
    settings_to_document,
    switch_user_sync_off,
    write_sync_settings,
)
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_TYPE_ID: int = 21
OVERRIDE_TYPE_ID: int = 22
GROUP_TYPE_ID: int = 23
FIRST_USER_ID: int = 3
SECOND_USER_ID: int = 9

CONFIGURED: PersonSyncSettings = PersonSyncSettings(
    users=UserSyncSettings(active=True, default_type_id=DEFAULT_TYPE_ID,
                           type_overrides={SECOND_USER_ID: OVERRIDE_TYPE_ID, FIRST_USER_ID: OVERRIDE_TYPE_ID}),
    groups=GroupSyncSettings(active=True, default_type_id=GROUP_TYPE_ID),
)
CONFIGURED_DOCUMENT: dict[str, Any] = {
    'users': {
        'active': True,
        'default_type_id': DEFAULT_TYPE_ID,
        'type_overrides': [
            {'user_id': FIRST_USER_ID, 'type_id': OVERRIDE_TYPE_ID},
            {'user_id': SECOND_USER_ID, 'type_id': OVERRIDE_TYPE_ID},
        ],
    },
    'groups': {'active': True, 'default_type_id': GROUP_TYPE_ID},
}


class TestReadingTheSection:
    """What a stored section, or none, reads as."""

    @pytest.mark.parametrize('document', [None, {}, {'_id': PERSON_SYNC_SETTINGS_SECTION}],
                             ids=['no-section', 'empty', 'id-only'])
    def test_nothing_stored_is_off_and_unchosen(self, document: dict[str, Any] | None) -> None:
        """A fresh system: both syncs off, no target"""
        assert settings_from_document(document) == PersonSyncSettings()
        assert PersonSyncSettings().users == UserSyncSettings(active=False, default_type_id=None, type_overrides={})

    def test_a_stored_section_is_read_whole(self) -> None:
        """Both halves and every override"""
        assert settings_from_document({'_id': PERSON_SYNC_SETTINGS_SECTION, **CONFIGURED_DOCUMENT}) == CONFIGURED

    @pytest.mark.parametrize('stored', [1, 'yes', None], ids=['one', 'string', 'null'])
    def test_only_true_switches_a_sync_on(self, stored: Any) -> None:
        """A switch is on only when it is the boolean true"""
        settings = settings_from_document({'users': {'active': stored}, 'groups': {'active': stored}})

        assert (settings.users.active, settings.groups.active) == (False, False)

    @pytest.mark.parametrize('overrides', [None, {'3': 22}, [{'user_id': FIRST_USER_ID}], ['entry']],
                             ids=['null', 'map', 'no-type', 'not-a-dict'])
    def test_unreadable_overrides_are_left_out(self, overrides: Any) -> None:
        """Only complete entries are overrides"""
        assert settings_from_document({'users': {'type_overrides': overrides}}).users.type_overrides == {}


class TestWritingTheSection:
    """The stored shape."""

    def test_the_settings_are_written_whole_with_the_overrides_in_user_order(self) -> None:
        """A list of entries, sorted by user id - stable whatever order the map was built in"""
        assert settings_to_document(CONFIGURED) == CONFIGURED_DOCUMENT

    def test_the_round_trip_keeps_the_settings(self) -> None:
        """Written and read back, nothing changes"""
        assert settings_from_document(settings_to_document(CONFIGURED)) == CONFIGURED

    def test_read_and_write_address_the_one_section(self) -> None:
        """The section's _id names it; the write stores both halves"""
        settings_manager = MagicMock()
        settings_manager.get_section.return_value = {'_id': PERSON_SYNC_SETTINGS_SECTION, **CONFIGURED_DOCUMENT}

        assert read_sync_settings(settings_manager) == CONFIGURED
        settings_manager.get_section.assert_called_once_with(PERSON_SYNC_SETTINGS_SECTION)

        write_sync_settings(settings_manager, CONFIGURED)
        settings_manager.write.assert_called_once_with(PERSON_SYNC_SETTINGS_SECTION, CONFIGURED_DOCUMENT)


class TestTargetsAndSwitchingOff:
    """The targets, and the user sync switched off."""

    def test_the_targets_are_the_default_and_the_overrides(self) -> None:
        """Each Type once"""
        assert CONFIGURED.users.target_type_ids() == {DEFAULT_TYPE_ID, OVERRIDE_TYPE_ID}

    def test_no_default_chosen_leaves_only_the_overrides(self) -> None:
        """An override chosen before the default"""
        users = UserSyncSettings(type_overrides={FIRST_USER_ID: OVERRIDE_TYPE_ID})

        assert users.target_type_ids() == {OVERRIDE_TYPE_ID}

    def test_switching_the_user_sync_off_switches_the_group_sync_off(self) -> None:
        """The group sync's members are the user sync's persons; the targets stay chosen"""
        switched = switch_user_sync_off(CONFIGURED)

        assert (switched.users.active, switched.groups.active) == (False, False)
        assert switched.users.default_type_id == DEFAULT_TYPE_ID
        assert switched.users.type_overrides == CONFIGURED.users.type_overrides
