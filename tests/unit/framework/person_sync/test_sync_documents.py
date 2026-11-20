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
Unit tests for cmdb.framework.person_sync.sync_documents

Pinned: a set value replaces an entry's value and stamps its kind, a missing entry is appended, the stored entries are
not changed; a new person carries the synced values, the Type's usable defaults, the PERSON marker, the link and the
fingerprint; a person after the sync keeps its own fields and takes the user's values, state and fingerprint; a mapped
group after the sync takes the name and members, the rest kept
"""
import copy
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.sync_mapping import SyncedPerson
from cmdb.framework.person_sync.sync_documents import (
    build_person_document,
    former_person,
    group_after_sync,
    group_without_members,
    linked_kind,
    linked_record_id,
    person_after_sync,
    system_ref_of,
    with_field_values,
)
from cmdb.models.object_model import SystemRefKind
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE_ID: int = 91
GROUP_TYPE_ID: int = 92
PERSON_ID: int = 501
USER_ID: int = 7
AUTHOR_ID: int = 1
OWN_FIELD: str = 'badge_number'
OWN_DEFAULT: str = 'B-000'
NOW: datetime = datetime(2026, 11, 19, tzinfo=timezone.utc)
SYNCED: SyncedPerson = SyncedPerson(values={
    PersonField.DISPLAY_NAME.value: 'Ann Lee', PersonField.FIRST_NAME.value: 'Ann',
    PersonField.LAST_NAME.value: 'Lee', PersonField.EMAIL.value: '',
}, active=True)


def _type(marker: SpecialType, type_id: int, own_default: bool = False) -> CmdbType:
    """A Type from the blueprint, optionally with an own text field that has a default"""
    document: dict[str, Any] = build_default_person_type(marker, f'type-{type_id}', type_id)

    if own_default:
        document['fields'].append({'type': 'text', 'name': OWN_FIELD, 'label': 'Badge', 'value': OWN_DEFAULT})
        document['render_meta']['sections'][0]['fields'].append(OWN_FIELD)

    return CmdbType.from_data(document)


def _values(document: dict[str, Any]) -> dict[str, Any]:
    """A document's values by field name"""
    return {entry['name']: entry['value'] for entry in document['fields']}


class TestWithFieldValues:
    """Setting values on field entries."""

    def test_a_value_replaces_and_a_missing_entry_is_appended(self) -> None:
        """Each set entry carries its kind"""
        entries = [{'name': 'a', 'value': 1, 'type': 'number'}, {'name': 'b', 'value': 'x', 'type': 'text'}]

        assert with_field_values(entries, {'b': 'y', 'c': 'z'}, {'b': 'text', 'c': 'text'}) == [
            {'name': 'a', 'value': 1, 'type': 'number'},
            {'name': 'b', 'value': 'y', 'type': 'text'},
            {'name': 'c', 'value': 'z', 'type': 'text'},
        ]

    def test_the_stored_entries_are_not_changed(self) -> None:
        """A copy is returned"""
        entries = [{'name': 'b', 'value': 'x', 'type': 'text'}]
        before = copy.deepcopy(entries)

        with_field_values(entries, {'b': 'y'}, {'b': 'text'})

        assert entries == before


class TestANewPerson:
    """The person the sync creates."""

    def test_it_is_complete(self) -> None:
        """Values, marker, link, fingerprint, the acting user as author"""
        document = build_person_document(PERSON_ID, _type(SpecialType.PERSON, PERSON_TYPE_ID), USER_ID, SYNCED,
                                         AUTHOR_ID, NOW)

        assert _values(document) == SYNCED.values
        assert (document['public_id'], document['type_id'], document['author_id'], document['creation_time'],
                document['special_type'], document['active']) == (PERSON_ID, PERSON_TYPE_ID, AUTHOR_ID, NOW,
                                                                  'PERSON', True)
        assert document['system_ref'] == system_ref_of(SystemRefKind.USER, USER_ID)
        assert document['sync_hash'] == SYNCED.fingerprint()

    def test_the_types_defaults_are_filled(self) -> None:
        """As the object create fills them"""
        document = build_person_document(PERSON_ID, _type(SpecialType.PERSON, PERSON_TYPE_ID, own_default=True),
                                         USER_ID, SYNCED, AUTHOR_ID, NOW)

        assert _values(document)[OWN_FIELD] == OWN_DEFAULT


class TestAfterTheSync:
    """A stored person or group after a sync."""

    def test_a_persons_own_field_stays(self) -> None:
        """And its values, state and fingerprint are the user's"""
        stored = {'public_id': PERSON_ID, 'active': True, 'sync_hash': 'old', 'fields': [
            {'name': PersonField.FIRST_NAME.value, 'value': 'Bo', 'type': 'text'},
            {'name': PersonField.PHONE_NUMBER.value, 'value': '555', 'type': 'text'},
        ]}
        deactivated = SyncedPerson(values=SYNCED.values, active=False)

        after = person_after_sync(stored, _type(SpecialType.PERSON, PERSON_TYPE_ID), deactivated)

        assert _values(after)[PersonField.PHONE_NUMBER.value] == '555'
        assert _values(after)[PersonField.FIRST_NAME.value] == 'Ann'
        assert (after['active'], after['sync_hash']) == (False, deactivated.fingerprint())
        assert stored['sync_hash'] == 'old'

    def test_a_groups_name_and_members_are_set(self) -> None:
        """Its email stays"""
        stored = {'public_id': PERSON_ID, 'active': True, 'fields': [
            {'name': PersonGroupField.NAME.value, 'value': 'old', 'type': 'text'},
            {'name': PersonGroupField.EMAIL.value, 'value': 'desk@example.org', 'type': 'text'},
        ]}

        after = group_after_sync(stored, _type(SpecialType.PERSON_GROUP, GROUP_TYPE_ID), 'Desk', [3, 4])

        assert _values(after) == {PersonGroupField.NAME.value: 'Desk',
                                  PersonGroupField.EMAIL.value: 'desk@example.org',
                                  PersonGroupField.MEMBERS.value: [3, 4]}
        assert next(entry for entry in after['fields']
                    if entry['name'] == PersonGroupField.MEMBERS.value)['type'] == 'person'


def test_a_former_person_is_unlinked_and_deactivated_with_its_values_kept() -> None:
    """Link and fingerprint gone, active False, everything else as stored; the stored one untouched"""
    stored: dict[str, Any] = {'public_id': PERSON_ID, 'type_id': PERSON_TYPE_ID, 'active': True,
                              'fields': [{'name': 'email', 'value': 'a'}],
                              'system_ref': {'kind': 'user', 'id': 9}, 'sync_hash': 'abc'}

    former = former_person(stored)

    assert former == {'public_id': PERSON_ID, 'type_id': PERSON_TYPE_ID, 'active': False,
                      'fields': [{'name': 'email', 'value': 'a'}]}
    assert stored['active'] is True and 'system_ref' in stored



@pytest.mark.parametrize('document, expected', [
    ({'system_ref': {'kind': 'user', 'id': 7}}, ('user', 7)),
    ({'system_ref': None}, (None, None)),
    ({}, (None, None)),
    ({'system_ref': 'broken'}, (None, None)),
], ids=['linked', 'null', 'absent', 'not-a-link'])
def test_the_link_accessors(document: dict[str, Any], expected: tuple[Any, Any]) -> None:
    """The kind and id of a linked object; None for any other"""
    assert (linked_kind(document), linked_record_id(document)) == expected


def test_a_group_without_members_keeps_its_name_and_the_rest() -> None:
    """Only the given persons go, the others keep their order"""
    group_type: CmdbType = _type(SpecialType.PERSON_GROUP, 2)
    stored: dict[str, Any] = {'public_id': 5, 'fields': [
        {'name': PersonGroupField.NAME.value, 'value': 'Ops', 'type': 'text'},
        {'name': PersonGroupField.MEMBERS.value, 'value': [4, 9, 3], 'type': 'person'},
    ]}

    after: dict[str, Any] = group_without_members(stored, group_type, {9})

    assert {entry['name']: entry['value'] for entry in after['fields']} == {
        PersonGroupField.NAME.value: 'Ops', PersonGroupField.MEMBERS.value: [4, 3]}
    assert stored['fields'][1]['value'] == [4, 9, 3]
