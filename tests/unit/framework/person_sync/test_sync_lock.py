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
Unit tests for cmdb.framework.person_sync.sync_lock

Pinned for a synced person: each synced field and the active state are locked, an empty value stays the same empty
value whatever its spelling, its own fields are free. For a mapped person group: the name and the synced members are
locked while the group sync is on - a hand-added person comes and goes - and nothing is locked while it is off. A
synced object keeps its Type; a create and an object that is not synced are never judged. ``enforce_sync_lock`` reads
nothing for those, and for a mapped group the settings and, only while the group sync is on, the members' links
"""
import copy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.framework.person_sync.person_sync_constants import SyncLockProblem
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings
from cmdb.framework.person_sync.sync_lock import enforce_sync_lock, locked_change_reasons
# -------------------------------------------------------------------------------------------------------------------- #

LOCK_PATH: str = 'cmdb.framework.person_sync.sync_lock'
PERSON_ID: int = 501
GROUP_OBJECT_ID: int = 502
USER_ID: int = 7
USER_GROUP_ID: int = 3
TYPE_ID: int = 40
OTHER_TYPE_ID: int = 41
SYNCED_MEMBER: int = 601
OTHER_SYNCED_MEMBER: int = 602
HAND_MEMBER: int = 701
SYNCED_IDS: set[int] = {SYNCED_MEMBER, OTHER_SYNCED_MEMBER}


def _person(**field_values: Any) -> dict[str, Any]:
    """A synced person, the given field values replaced"""
    values: dict[str, Any] = {
        PersonField.DISPLAY_NAME.value: 'Ann Lee', PersonField.FIRST_NAME.value: 'Ann',
        PersonField.LAST_NAME.value: 'Lee', PersonField.EMAIL.value: '', PersonField.PHONE_NUMBER.value: '123',
    }
    values.update(field_values)

    return {
        'public_id': PERSON_ID, 'type_id': TYPE_ID, 'active': True,
        'system_ref': {'kind': 'user', 'id': USER_ID},
        'fields': [{'name': name, 'value': value, 'type': 'text'} for name, value in values.items()],
    }


def _group(name: str = 'Service Desk', members: list[int] | None = None) -> dict[str, Any]:
    """A mapped person group"""
    return {
        'public_id': GROUP_OBJECT_ID, 'type_id': TYPE_ID, 'active': True,
        'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID},
        'fields': [
            {'name': PersonGroupField.NAME.value, 'value': name, 'type': 'text'},
            {'name': PersonGroupField.MEMBERS.value,
             'value': [SYNCED_MEMBER, HAND_MEMBER] if members is None else members, 'type': 'person'},
        ],
    }


def _person_fields_reason(names: list[str]) -> str:
    """The refusal naming the person's changed synced fields"""
    return SyncLockProblem.PERSON_FIELDS.value.format(public_id=PERSON_ID, user_id=USER_ID, names=names)


class TestASyncedPerson:
    """Its synced fields and active state are its user's."""

    @pytest.mark.parametrize('name', [PersonField.DISPLAY_NAME.value, PersonField.FIRST_NAME.value,
                                      PersonField.LAST_NAME.value, PersonField.EMAIL.value])
    def test_each_synced_field_is_locked(self, name: str) -> None:
        """Whoever writes, whatever their rights"""
        assert locked_change_reasons(_person(), _person(**{name: 'changed'})) == [_person_fields_reason([name])]

    def test_every_changed_field_is_named_in_order(self) -> None:
        """One reason for the fields"""
        candidate = _person(**{PersonField.EMAIL.value: 'a@b.org', PersonField.FIRST_NAME.value: 'Bo'})

        assert locked_change_reasons(_person(), candidate) == [
            _person_fields_reason([PersonField.FIRST_NAME.value, PersonField.EMAIL.value]),
        ]

    def test_its_own_field_is_free(self) -> None:
        """The phone number is the person's"""
        assert locked_change_reasons(_person(), _person(**{PersonField.PHONE_NUMBER.value: '456'})) == []

    @pytest.mark.parametrize('empty', [None, ''], ids=['null', 'empty-string'])
    def test_an_empty_value_spelled_otherwise_is_no_change(self, empty: Any) -> None:
        """'' stored, null sent - the same empty value"""
        assert locked_change_reasons(_person(), _person(**{PersonField.EMAIL.value: empty})) == []

    def test_an_absent_field_reads_as_empty(self) -> None:
        """A candidate without the empty email entry changes nothing"""
        candidate = _person()
        candidate['fields'] = [entry for entry in candidate['fields'] if entry['name'] != PersonField.EMAIL.value]

        assert locked_change_reasons(_person(), candidate) == []

    def test_the_active_state_is_locked(self) -> None:
        """A deactivated user's person stays deactivated"""
        assert locked_change_reasons(_person(), {**_person(), 'active': False}) == [
            SyncLockProblem.PERSON_ACTIVE.value.format(public_id=PERSON_ID, user_id=USER_ID),
        ]

    def test_it_is_locked_whatever_the_group_sync(self) -> None:
        """The person lock does not depend on any switch"""
        assert locked_change_reasons(_person(), _person(**{PersonField.LAST_NAME.value: 'Li'}), False, set())


class TestAMappedPersonGroup:
    """Its name and its synced members are its user group's - while the group sync is on."""

    def test_the_name_is_locked(self) -> None:
        """The user group's label decides it"""
        assert locked_change_reasons(_group(), _group(name='Desk'), True, SYNCED_IDS) == [
            SyncLockProblem.GROUP_NAME.value.format(public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID),
        ]

    def test_a_synced_member_is_not_removed_by_hand(self) -> None:
        """Only its user leaving the user group removes it"""
        assert locked_change_reasons(_group(), _group(members=[HAND_MEMBER]), True, SYNCED_IDS) == [
            SyncLockProblem.GROUP_MEMBERS.value.format(public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID,
                                                       added=[], removed=[SYNCED_MEMBER]),
        ]

    def test_a_synced_person_is_not_added_by_hand(self) -> None:
        """Only its user joining the user group adds it"""
        candidate = _group(members=[SYNCED_MEMBER, HAND_MEMBER, OTHER_SYNCED_MEMBER])

        assert locked_change_reasons(_group(), candidate, True, SYNCED_IDS) == [
            SyncLockProblem.GROUP_MEMBERS.value.format(public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID,
                                                       added=[OTHER_SYNCED_MEMBER], removed=[]),
        ]

    def test_a_hand_added_member_comes_and_goes(self) -> None:
        """A person that is not synced is the group's own"""
        assert locked_change_reasons(_group(), _group(members=[SYNCED_MEMBER]), True, SYNCED_IDS) == []

    def test_the_order_of_the_members_is_no_change(self) -> None:
        """The same persons"""
        assert locked_change_reasons(_group(), _group(members=[HAND_MEMBER, SYNCED_MEMBER]), True, SYNCED_IDS) == []

    def test_nothing_is_locked_while_the_group_sync_is_off(self) -> None:
        """Off means unlocked"""
        candidate = _group(name='Desk', members=[OTHER_SYNCED_MEMBER])

        assert locked_change_reasons(_group(), candidate, False, SYNCED_IDS) == []


class TestEverySyncedObject:
    """What holds for both kinds, and what is never judged."""

    @pytest.mark.parametrize('stored', [_person(), _group()], ids=['person', 'group'])
    def test_it_keeps_its_type(self, stored: dict[str, Any]) -> None:
        """The import's overwrite may re-type an object - not a synced one"""
        candidate = {**copy.deepcopy(stored), 'type_id': OTHER_TYPE_ID}

        assert SyncLockProblem.TYPE.value.format(public_id=stored['public_id']) in locked_change_reasons(
            stored, candidate)

    def test_a_create_is_never_judged(self) -> None:
        """No stored object, no lock"""
        assert locked_change_reasons(None, _person()) == []

    def test_an_object_that_is_not_synced_is_never_judged(self) -> None:
        """A person written by hand stays an ordinary object"""
        stored = _person()
        del stored['system_ref']

        assert locked_change_reasons(stored, _person(**{PersonField.FIRST_NAME.value: 'Bo'})) == []


class TestEnforceSyncLock:
    """What the lock reads."""

    @staticmethod
    def _objects_manager(synced_found: list[int]) -> MagicMock:
        """An ObjectsManager whose member query finds the given synced persons"""
        objects_manager = MagicMock()
        objects_manager.find.return_value = [{'public_id': member} for member in synced_found]

        return objects_manager

    def test_a_create_or_an_ordinary_object_reads_nothing(self) -> None:
        """The common write costs nothing"""
        objects_manager = self._objects_manager([])
        stored = _person()
        del stored['system_ref']

        with patch(f'{LOCK_PATH}.read_sync_settings') as read:
            assert enforce_sync_lock(objects_manager, _person(), None) is None
            assert enforce_sync_lock(objects_manager, _person(), stored) is None

        read.assert_not_called()
        objects_manager.find.assert_not_called()

    def test_a_person_reads_nothing_and_joins_the_reasons(self) -> None:
        """Both reasons in one message"""
        objects_manager = self._objects_manager([])
        candidate = {**_person(**{PersonField.FIRST_NAME.value: 'Bo'}), 'active': False}

        with patch(f'{LOCK_PATH}.read_sync_settings') as read:
            message = enforce_sync_lock(objects_manager, candidate, _person())

        assert message == ' '.join([
            _person_fields_reason([PersonField.FIRST_NAME.value]),
            SyncLockProblem.PERSON_ACTIVE.value.format(public_id=PERSON_ID, user_id=USER_ID),
        ])
        read.assert_not_called()
        objects_manager.find.assert_not_called()

    def test_a_mapped_group_reads_the_settings_then_its_members_links(self) -> None:
        """One query over the stored and the new members, synced persons only"""
        objects_manager = self._objects_manager([SYNCED_MEMBER])
        settings = PersonSyncSettings(groups=GroupSyncSettings(active=True))

        with patch(f'{LOCK_PATH}.read_sync_settings', return_value=settings):
            message = enforce_sync_lock(objects_manager, _group(members=[HAND_MEMBER]), _group())

        assert message == SyncLockProblem.GROUP_MEMBERS.value.format(
            public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID, added=[], removed=[SYNCED_MEMBER])
        objects_manager.find.assert_called_once_with(
            criteria={'public_id': {'$in': [SYNCED_MEMBER, HAND_MEMBER]}, 'system_ref.kind': 'user'},
            projection={'public_id': 1},
        )

    def test_a_mapped_group_with_the_group_sync_off_reads_no_member(self) -> None:
        """Unlocked - nothing to judge"""
        objects_manager = self._objects_manager([SYNCED_MEMBER])

        with patch(f'{LOCK_PATH}.read_sync_settings', return_value=PersonSyncSettings()):
            assert enforce_sync_lock(objects_manager, _group(name='Desk', members=[]), _group()) is None

        objects_manager.find.assert_not_called()
