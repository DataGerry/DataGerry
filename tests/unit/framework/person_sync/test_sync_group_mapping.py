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
Unit tests for cmdb.framework.person_sync.sync_group_mapping and the person group the sync creates

Pinned: the mappings are read in user group order from one read; an existing object is refused when missing, no person
group or mapped already; a Type for a new one when missing, without PERSON_GROUP, deactivated or requiring a field
the sync cannot fill; mapping links an existing group into the ledger or creates one, and the group sync follows
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import GroupMappingProblem, PersonSyncProblem
from cmdb.framework.person_sync.sync_documents import build_person_group_document
from cmdb.framework.person_sync.sync_engine import SyncContext, SyncResult
from cmdb.framework.person_sync.sync_group_mapping import (
    existing_person_group_problems,
    map_user_group,
    person_group_type_problems,
    read_group_mappings,
)
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.framework.person_sync.sync_group_mapping'
GROUP_TYPE_ID: int = 41
PERSON_TYPE_ID: int = 42
OBJECT_ID: int = 51
NEW_ID: int = 52
USER_GROUP_ID: int = 61
OTHER_USER_GROUP_ID: int = 62
AUTHOR_ID: int = 1
OWN_FIELD: str = 'cost_center'
LABEL: str = 'Field Service'
ACTING: CmdbUser = CmdbUser(public_id=AUTHOR_ID, user_name='admin', active=True)
USER_GROUP: CmdbUserGroup = CmdbUserGroup(public_id=USER_GROUP_ID, name='field', label=LABEL)


def _group_type(active: bool = True, own_required: bool = False) -> CmdbType:
    """A Type from the PERSON_GROUP blueprint, optionally with a required own field without default"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON_GROUP, 'groups', GROUP_TYPE_ID)
    document['active'] = active

    if own_required:
        document['fields'].append({'type': 'text', 'name': OWN_FIELD, 'label': 'Cost center', 'required': True})

    return CmdbType.from_data(document)


def _context() -> SyncContext:
    """Mocked managers, both syncs off"""
    return SyncContext(MagicMock(), MagicMock(), MagicMock(), MagicMock(), PersonSyncSettings(), ACTING)


class TestReadGroupMappings:
    """One read, user group order."""

    def test_the_links_are_answered_in_user_group_order(self) -> None:
        """Both ids per mapping"""
        objects_manager = MagicMock()
        objects_manager.find.return_value = [
            {'public_id': NEW_ID, 'system_ref': {'kind': 'user_group', 'id': OTHER_USER_GROUP_ID}},
            {'public_id': OBJECT_ID, 'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID}},
        ]

        assert read_group_mappings(objects_manager) == [
            {'user_group_id': USER_GROUP_ID, 'person_group_id': OBJECT_ID},
            {'user_group_id': OTHER_USER_GROUP_ID, 'person_group_id': NEW_ID},
        ]
        assert objects_manager.find.call_args.kwargs['criteria'] == {'system_ref.kind': 'user_group'}


class TestExistingPersonGroupProblems:
    """An existing object chosen to mirror a user group."""

    def test_an_unmapped_person_group_passes(self) -> None:
        """Nothing to refuse"""
        assert existing_person_group_problems(OBJECT_ID, {'special_type': SpecialType.PERSON_GROUP.value}) == []
        assert existing_person_group_problems(
            OBJECT_ID, {'special_type': SpecialType.PERSON_GROUP.value, 'active': True}) == []

    @pytest.mark.parametrize('stored, expected', [
        (None, GroupMappingProblem.OBJECT_MISSING.value.format(public_id=OBJECT_ID)),
        ({'special_type': SpecialType.PERSON.value}, GroupMappingProblem.NOT_PERSON_GROUP.value.format(
            public_id=OBJECT_ID)),
        ({}, GroupMappingProblem.NOT_PERSON_GROUP.value.format(public_id=OBJECT_ID)),
        ({'special_type': SpecialType.PERSON_GROUP.value, 'system_ref': {'kind': 'user_group', 'id': 7}},
         GroupMappingProblem.PERSON_GROUP_MAPPED.value.format(public_id=OBJECT_ID, user_group_id=7)),
        ({'special_type': SpecialType.PERSON_GROUP.value, 'active': False},
         GroupMappingProblem.PERSON_GROUP_INACTIVE.value.format(public_id=OBJECT_ID)),
    ], ids=['missing', 'a-person', 'no-marker', 'mapped', 'deactivated'])
    def test_a_refused_object_names_why(self, stored: dict[str, Any] | None, expected: str) -> None:
        """One problem"""
        assert existing_person_group_problems(OBJECT_ID, stored) == [expected]


class TestPersonGroupTypeProblems:
    """The Type a new mapped person group is created in."""

    def test_the_blueprint_passes(self) -> None:
        """Name and members are filled"""
        assert person_group_type_problems(GROUP_TYPE_ID, _group_type()) == []

    def test_a_missing_type(self) -> None:
        """Only that"""
        assert person_group_type_problems(GROUP_TYPE_ID, None) == [
            PersonSyncProblem.TYPE_MISSING.value.format(type_id=GROUP_TYPE_ID)]

    def test_a_person_type(self) -> None:
        """No PERSON_GROUP marker"""
        person_type = CmdbType.from_data(build_default_person_type(SpecialType.PERSON, 'persons', PERSON_TYPE_ID))

        assert person_group_type_problems(PERSON_TYPE_ID, person_type) == [
            GroupMappingProblem.TYPE_NOT_PERSON_GROUP.value.format(type_id=PERSON_TYPE_ID)]

    def test_a_deactivated_type_with_an_unfillable_field_names_both(self) -> None:
        """Every problem at once"""
        assert person_group_type_problems(GROUP_TYPE_ID, _group_type(active=False, own_required=True)) == [
            PersonSyncProblem.TYPE_INACTIVE.value.format(type_id=GROUP_TYPE_ID),
            PersonSyncProblem.TYPE_UNFILLABLE_FIELDS.value.format(type_id=GROUP_TYPE_ID, names=[OWN_FIELD]),
        ]


class TestBuildPersonGroupDocument:
    """The person group the sync creates."""

    def test_named_linked_and_without_members(self) -> None:
        """The marker, the link, the name; no fingerprint"""
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)

        document = build_person_group_document(NEW_ID, _group_type(), USER_GROUP_ID, LABEL, AUTHOR_ID, now)

        assert document['public_id'] == NEW_ID
        assert document['type_id'] == GROUP_TYPE_ID
        assert document['special_type'] == SpecialType.PERSON_GROUP.value
        assert document['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}
        assert (document['author_id'], document['creation_time'], document['active']) == (AUTHOR_ID, now, True)
        values: dict[str, Any] = {entry['name']: entry['value'] for entry in document['fields']}
        assert values[PersonGroupField.NAME.value] == LABEL
        assert values[PersonGroupField.MEMBERS.value] == []
        assert 'sync_hash' not in document


class TestMapUserGroup:
    """Link or create, then the group sync."""

    def test_an_existing_group_is_linked_into_the_ledger(self) -> None:
        """One update setting the link; its prior state recorded"""
        context, ledger = _context(), MagicMock()
        stored: dict[str, Any] = {'public_id': OBJECT_ID, 'special_type': SpecialType.PERSON_GROUP.value}

        with patch(f'{MODULE}.sync_user_group', return_value=SyncResult()) as synced:
            public_id, result = map_user_group(context, ledger, USER_GROUP, person_group=stored)

        assert public_id == OBJECT_ID
        assert result.created == []
        context.objects_manager.update.assert_called_once_with(
            {'public_id': OBJECT_ID}, {'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID}})
        ledger.updated.assert_called_once_with(context.objects_manager, OBJECT_ID, stored)
        synced.assert_called_once_with(context, ledger, USER_GROUP)

    def test_a_new_group_is_created_and_counted(self) -> None:
        """Inserted with the next id, recorded, answered as created"""
        context, ledger = _context(), MagicMock()
        context.objects_manager.get_new_object_public_id.return_value = NEW_ID

        with patch(f'{MODULE}.sync_user_group', return_value=SyncResult()):
            public_id, result = map_user_group(context, ledger, USER_GROUP, type_instance=_group_type())

        assert public_id == NEW_ID
        assert result.created == [NEW_ID]
        inserted: dict[str, Any] = context.objects_manager.insert.call_args.args[0]
        assert inserted['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}
        ledger.inserted.assert_called_once_with(context.objects_manager, NEW_ID)

    def test_the_group_syncs_edits_are_answered(self) -> None:
        """Merged into the result"""
        edit = MagicMock()

        with patch(f'{MODULE}.sync_user_group', return_value=SyncResult(edits={OBJECT_ID: edit})):
            _, result = map_user_group(_context(), MagicMock(), USER_GROUP, person_group={'public_id': OBJECT_ID})

        assert result.edits == {OBJECT_ID: edit}

    def test_neither_target_is_a_programming_error(self) -> None:
        """Nothing written"""
        context = _context()

        with pytest.raises(ValueError):
            map_user_group(context, MagicMock(), USER_GROUP)

        context.objects_manager.update.assert_not_called()
        context.objects_manager.insert.assert_not_called()
