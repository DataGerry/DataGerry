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
Unit tests for cmdb.database.updater.versions.updater_20261119

The pure rules of the person migration - the rights matching and the ACL they become, the object values, the object
document, the ISMS reference rewrite, the membership report and the log entry - and the update's flow: no old
collections, nothing but the version; a renamed database skips the records and the references; a failure is wrapped
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261119 as module
from cmdb.database.updater.versions.updater_20261119 import (
    Update20261119,
    build_object,
    creation_log_entry,
    granted_permissions,
    group_values,
    holds_right,
    membership_disagreements,
    merged_acl,
    missing_object_rights,
    person_values,
    rewritten_references,
)
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

PERSON: str = module.PERSON
GROUP: str = module.PERSON_GROUP
EVERYTHING: list[str] = ['CREATE', 'READ', 'UPDATE', 'DELETE']
NOW: datetime = datetime(2026, 1, 2, tzinfo=timezone.utc)
ID_MAPS: dict[str, dict[int, int]] = {PERSON: {1: 101, 2: 102}, GROUP: {1: 201}}


def _update() -> Update20261119:
    """An update without a database - every collaborator mocked"""
    update = Update20261119.__new__(Update20261119)
    update.dbm = MagicMock()
    update.db_name = 'test'
    update.increase_updater_version = MagicMock()

    return update

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       rights                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('rights, expected', [
    (['base.user-management.person.view'], True),
    (['base.user-management.person.*'], True),
    (['base.user-management.*'], True),
    (['base.*'], True),
    (['base.user-management.personGroup.view'], False),
    (['base.user-management.personGroup.*'], False),
    (['base.framework.*'], False),
    ([], False),
], ids=str)
def test_holds_right(rights: list[str], expected: bool) -> None:
    """The name itself or a wildcard of any parent; a sibling's wildcard is no grant"""
    assert holds_right(rights, 'base.user-management.person.view') is expected


def test_granted_permissions_in_a_fixed_order() -> None:
    """add / view / edit / delete become CREATE / READ / UPDATE / DELETE, ordered as the ACL orders them"""
    assert granted_permissions(['base.user-management.person.delete', 'base.user-management.person.view'],
                               PERSON) == ['READ', 'DELETE']
    assert granted_permissions(['base.*'], GROUP) == EVERYTHING
    assert not granted_permissions(['base.user-management.person.*'], GROUP)


def test_missing_object_rights_names_each_unusable_permission() -> None:
    """READ without object.view is reported; a wildcard covers"""
    assert missing_object_rights(['base.framework.object.view'], ['READ', 'UPDATE']) == ['base.framework.object.edit']
    assert not missing_object_rights(['base.framework.*'], EVERYTHING)


def test_merged_acl_unions_per_group_and_switches_it_on() -> None:
    """Kept entries stay, new ones join as a set in ACL order"""
    stored = {'activated': False, 'groups': {'includes': {'1': ['READ'], '3': ['DELETE']}}}

    assert merged_acl(stored, {1: ['UPDATE', 'READ'], 2: ['READ']}) == {'activated': True, 'groups': {'includes': {
        '1': ['READ', 'UPDATE'], '2': ['READ'], '3': ['DELETE']}}}


@pytest.mark.parametrize('stored', [None, 'junk', {'groups': None}], ids=str)
def test_merged_acl_reads_an_unusable_stored_acl_as_empty(stored: Any) -> None:
    """Only the grants"""
    assert merged_acl(stored, {4: ['READ']}) == {'activated': True, 'groups': {'includes': {'4': ['READ']}}}


def test_merged_acl_with_no_grant_is_on_and_empty() -> None:
    """Nobody held the rights: nobody gets in"""
    assert merged_acl(None, {}) == {'activated': True, 'groups': {'includes': {}}}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the objects                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_person_values_fill_the_base_fields_but_user() -> None:
    """A missing key is empty; groups are not carried"""
    assert person_values({'display_name': 'A', 'first_name': 'B', 'groups': [1]}) == {
        'display_name': 'A', 'first_name': 'B', 'last_name': None, 'phone_number': None, 'email': None,
    }


def test_group_values_map_the_members_once_each_and_report_the_unknown() -> None:
    """Order kept, a repeated member once, an unmapped id reported"""
    values, unknown = group_values({'name': 'Ops', 'email': '', 'group_members': [2, 1, 2, 9]}, ID_MAPS[PERSON])

    assert values == {'name': 'Ops', 'email': '', 'members': [102, 101]}
    assert unknown == [9]


def test_group_values_without_members() -> None:
    """A null list is an empty selection"""
    assert group_values({'name': 'x', 'group_members': None}, {})[0]['members'] == []


def test_build_object_carries_every_type_field() -> None:
    """Values by name, a field without one empty, the kind from the Type, the marker, the system the author"""
    object_type = {'public_id': 7, 'special_type': PERSON,
                   'fields': [{'name': 'display_name', 'type': 'text'}, {'name': 'user', 'type': 'number'}]}

    document = build_object(40, object_type, {'display_name': 'A'}, NOW)

    assert document['fields'] == [{'name': 'display_name', 'value': 'A', 'type': 'text'},
                                  {'name': 'user', 'value': None, 'type': 'number'}]
    assert (document['public_id'], document['type_id'], document['special_type'], document['author_id'],
            document['creation_time'], document['active']) == (40, 7, PERSON, module.SYSTEM_AUTHOR_ID, NOW, True)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the ISMS references                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_risk_assessment_is_rewritten_by_its_ref_types() -> None:
    """Person 1 and group 1 map apart; a dangling id is emptied and counted; None stays untouched"""
    document = {'risk_owner_id': 1, 'risk_owner_id_ref_type': PERSON,
                'responsible_persons_id': 1, 'responsible_persons_id_ref_type': GROUP,
                'auditor_id': None, 'risk_assessor_id': 5, 'interviewed_persons': [2, 8, 1]}

    updates, dropped = rewritten_references(document, module.RISK_ASSESSMENTS, ID_MAPS)

    assert updates == {'risk_owner_id': 101, 'responsible_persons_id': 201, 'risk_assessor_id': None,
                       'interviewed_persons': [102, 101]}
    assert dropped == 2


def test_an_absent_list_is_not_added() -> None:
    """Only keys the document carries are written"""
    assert rewritten_references({}, module.RISK_ASSESSMENTS, ID_MAPS) == ({}, 0)


def test_an_unknown_ref_type_empties_the_reference() -> None:
    """Neither map applies"""
    document = {'responsible_for_implementation_id': 1, 'responsible_for_implementation_id_ref_type': 'OTHER'}

    assert rewritten_references(document, module.CONTROL_MEASURE_ASSIGNMENTS, ID_MAPS) == (
        {'responsible_for_implementation_id': None}, 1)


def test_membership_disagreements_count_what_only_the_person_lists() -> None:
    """Person 1 lists group 1 which names it; person 2 lists group 1 and an unknown group"""
    persons = [{'public_id': 1, 'groups': [1]}, {'public_id': 2, 'groups': [1, 3]}, {'public_id': 4}]

    assert membership_disagreements(persons, [{'public_id': 1, 'group_members': [1]}]) == 2


def test_creation_log_entry_is_the_systems() -> None:
    """Object, version and type from the render; the system as user; the render stored as JSON bytes"""
    render = SimpleNamespace(object_information={'object_id': 40, 'version': '1.0.0'},
                             type_information={'type_id': 7})

    entry = creation_log_entry(render)

    assert (entry['object_id'], entry['version'], entry['type_id'], entry['user_id'], entry['user_name'],
            entry['comment']) == (40, '1.0.0', 7, module.SYSTEM_AUTHOR_ID, module.SYSTEM_USER_NAME, module.LOG_COMMENT)
    assert isinstance(entry['render_state'], bytes)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      the flow                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_without_the_old_collections_only_the_version_is_written() -> None:
    """A staging database: nothing migrated"""
    update = _update()
    update._has_legacy_collections = MagicMock(return_value=False)  # pylint: disable=protected-access
    update._migrate = MagicMock()  # pylint: disable=protected-access

    update.start_update()

    update._migrate.assert_not_called()  # pylint: disable=protected-access
    update.increase_updater_version.assert_called_once_with(20261119)


def test_a_renamed_database_skips_the_records_and_the_references() -> None:
    """Only the logs, the rights, the rename and the flags run"""
    update = _update()
    calls: list[str] = []

    for name in ('_write_creation_logs', '_grant_person_rights', '_rename_legacy', '_clear_isms_flags',
                 '_migrate_records', '_rewrite_isms'):
        setattr(update, name, MagicMock(side_effect=lambda *_a, n=name: calls.append(n)))

    update._default_types = MagicMock(return_value={})  # pylint: disable=protected-access
    update._renamed = MagicMock(return_value=True)  # pylint: disable=protected-access

    update._migrate()  # pylint: disable=protected-access

    assert calls == ['_write_creation_logs', '_grant_person_rights', '_rename_legacy', '_clear_isms_flags']


def test_a_failure_is_wrapped_and_the_version_is_not_written() -> None:
    """The updater tail: the exception itself, chained"""
    update = _update()
    failure = RuntimeError('down')
    update._has_legacy_collections = MagicMock(side_effect=failure)  # pylint: disable=protected-access

    with pytest.raises(UpdaterException) as raised:
        update.start_update()

    assert raised.value.__cause__ is failure
    update.increase_updater_version.assert_not_called()


@pytest.mark.parametrize('renamed, records, expected', [
    (True, None, True), (False, {'_id': 1}, True), (False, None, False),
], ids=['renamed', 'a-record', 'empty'])
def test_what_counts_as_something_to_migrate(renamed: bool, records: Any, expected: bool) -> None:
    """A renamed collection (a stopped run) or an old record; empty old collections are nothing"""
    update = _update()
    update._renamed = MagicMock(return_value=renamed)  # pylint: disable=protected-access
    update.dbm.get_collection.return_value.find_one.return_value = records

    assert update._has_legacy_collections() is expected  # pylint: disable=protected-access
