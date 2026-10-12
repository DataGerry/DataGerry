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
Unit tests for cmdb.framework.person.directory

Pure tests with the in-memory managers of tests.utils.person_stubs. Covered here are the lookups the stub
can evaluate (top-level equality / '$in') and the pure converters; the '$elemMatch' / '$or' lookups
(memberships, assignments) run against Mongo in the person relation route tests:

  - resolve_person_kinds / get_person_labels answer only ids of person and group objects, in one query
  - list_candidates honours the PersonRefKind and the denied types, sorted by label
  - the legacy shapes of GET /persons and GET /person_groups
  - the ISMS report '$lookup' stage
"""
from typing import Any

import pytest

from cmdb.framework.person.directory import (
    get_member_ids,
    get_person_labels,
    get_person_type_ids,
    list_candidates,
    list_person_objects,
    object_label,
    person_lookup_stage,
    resolve_person_kinds,
    to_legacy_person,
    to_legacy_person_group,
)
from tests.utils.person_stubs import (
    PERSON_GROUP_TYPE_ID,
    PERSON_TYPE_ID,
    StubObjectsManager,
    StubTypesManager,
    group_object,
    person_object,
    person_managers,
    selection,
)
# -------------------------------------------------------------------------------------------------------------------- #

ADA: int = 100
BOB: int = 101
NAMELESS: int = 102
SECURITY: int = 200
AUDIT: int = 201
SERVER: int = 300


@pytest.fixture(name='managers')
def fixture_managers() -> tuple[StubObjectsManager, StubTypesManager]:
    """Three persons (one without a name), two groups and an ordinary object"""
    return person_managers(
        person_object(ADA, 'Ada Lovelace', **{'dg-person-email': 'ada@example.com'}),
        person_object(BOB, 'bob'),
        person_object(NAMELESS, '  '),
        group_object(SECURITY, 'Security', [ADA, BOB]),
        group_object(AUDIT, 'audit', []),
        {'public_id': SERVER, 'type_id': 1, 'fields': []},
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 type and kind lookups                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_person_type_ids(managers: Any) -> None:
    """One list per person SpecialType"""
    _, types_manager = managers

    assert get_person_type_ids(types_manager) == {'PERSON': [PERSON_TYPE_ID], 'PERSON_GROUP': [PERSON_GROUP_TYPE_ID]}


def test_get_person_type_ids_before_the_types_exist() -> None:
    """Empty lists while an administrator has not created the types"""
    assert get_person_type_ids(StubTypesManager([])) == {'PERSON': [], 'PERSON_GROUP': []}


def test_resolve_person_kinds_answers_only_persons_and_groups(managers: Any) -> None:
    """An ordinary object and an unknown id are absent"""
    objects_manager, types_manager = managers

    kinds = resolve_person_kinds(objects_manager, types_manager, [ADA, SECURITY, SERVER, 999, ADA])

    assert kinds == {ADA: 'PERSON', SECURITY: 'PERSON_GROUP'}
    assert len(objects_manager.find_calls) == 1


def test_resolve_person_kinds_of_nothing_queries_nothing(managers: Any) -> None:
    """No ids, no query - not even for the types"""
    objects_manager, types_manager = managers

    assert resolve_person_kinds(objects_manager, types_manager, []) == {}
    assert not objects_manager.find_calls
    assert not types_manager.special_type_calls


def test_resolve_person_kinds_without_person_types_queries_no_object() -> None:
    """Nothing can be a person before the types exist"""
    objects_manager = StubObjectsManager([person_object(ADA, 'Ada')])

    assert resolve_person_kinds(objects_manager, StubTypesManager([]), [ADA]) == {}
    assert not objects_manager.find_calls


def test_resolve_person_kinds_accepts_a_generator(managers: Any) -> None:
    """The enforcement passes a generator expression"""
    objects_manager, types_manager = managers

    assert resolve_person_kinds(objects_manager, types_manager, (object_id for object_id in [BOB])) == {BOB: 'PERSON'}


def test_get_person_labels(managers: Any) -> None:
    """The full name or group name; '#<id>' for a blank one; other objects absent"""
    objects_manager, types_manager = managers

    labels = get_person_labels(objects_manager, types_manager, [ADA, NAMELESS, AUDIT, SERVER])

    assert labels == {ADA: 'Ada Lovelace', NAMELESS: f'#{NAMELESS}', AUDIT: 'audit'}


def test_get_person_labels_of_nothing(managers: Any) -> None:
    """No ids, no query"""
    objects_manager, types_manager = managers

    assert get_person_labels(objects_manager, types_manager, []) == {}
    assert not objects_manager.find_calls


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     object_label                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('document, kind, expected', [
    (person_object(1, 'Ada'), 'PERSON', 'Ada'),
    (group_object(2, 'Ops'), 'PERSON_GROUP', 'Ops'),
    (person_object(3, ''), 'PERSON', '#3'),
    (person_object(4, None), 'PERSON', '#4'),
    (person_object(5, 42), 'PERSON', '#5'),
    (person_object(6, 'Ada'), None, '#6'),
    (group_object(7, 'Ops'), 'PERSON', '#7'),
])
def test_object_label(document: dict[str, Any], kind: str | None, expected: str) -> None:
    """The label field of the kind, '#<id>' when it is empty, not text or the kind is no person kind"""
    assert object_label(document, kind) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  candidates / listing                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_list_candidates_of_both_kinds_sorted_by_label(managers: Any) -> None:
    """Case-insensitive by label (a blank name sorts as its '#<id>'), then by id"""
    objects_manager, types_manager = managers

    candidates = list_candidates(objects_manager, types_manager, 'BOTH')

    assert [(entry['ref_type'], entry['id']) for entry in candidates] == [
        ('PERSON', NAMELESS), ('PERSON', ADA), ('PERSON_GROUP', AUDIT), ('PERSON', BOB), ('PERSON_GROUP', SECURITY),
    ]
    assert candidates[1] == {'ref_type': 'PERSON', 'id': ADA, 'label': 'Ada Lovelace', 'type_id': PERSON_TYPE_ID}


@pytest.mark.parametrize('ref_kind, expected', [
    ('PERSON', {NAMELESS, ADA, BOB}),
    ('PERSON_GROUP', {SECURITY, AUDIT}),
])
def test_list_candidates_of_one_kind(managers: Any, ref_kind: str, expected: set[int]) -> None:
    """A restricted field only offers its kind"""
    objects_manager, types_manager = managers

    assert {entry['id'] for entry in list_candidates(objects_manager, types_manager, ref_kind)} == expected


def test_list_candidates_leaves_out_denied_types(managers: Any) -> None:
    """A type the caller may not read contributes nothing"""
    objects_manager, types_manager = managers

    candidates = list_candidates(objects_manager, types_manager, 'BOTH', denied_type_ids=[PERSON_TYPE_ID])

    assert {entry['ref_type'] for entry in candidates} == {'PERSON_GROUP'}


def test_list_person_objects_with_every_type_denied_queries_nothing(managers: Any) -> None:
    """No readable type, no query"""
    objects_manager, types_manager = managers

    assert list_person_objects(objects_manager, types_manager, 'PERSON', [PERSON_TYPE_ID]) == []
    assert not objects_manager.find_calls


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   members / legacy                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_member_ids_in_stored_order() -> None:
    """The person ids of the MEMBERS field"""
    assert get_member_ids(group_object(1, 'G', [5, 3, 4])) == [5, 3, 4]


def test_get_member_ids_skips_what_is_no_person() -> None:
    """A group selection or junk in the MEMBERS field is no member"""
    group = group_object(1, 'G', [5])
    group['fields'][2]['value'] += [selection('PERSON_GROUP', 9), 'junk', selection('PERSON', 'x')]

    assert get_member_ids(group) == [5]


def test_get_member_ids_of_a_group_without_the_field() -> None:
    """A group document missing its MEMBERS entry has no members"""
    assert get_member_ids({'public_id': 1, 'type_id': PERSON_GROUP_TYPE_ID, 'fields': []}) == []


def test_to_legacy_person() -> None:
    """The former management.person shape; missing or non-text values read as ''"""
    document = person_object(
        ADA, 'Ada Lovelace',
        **{'dg-person-first-name': 'Ada', 'dg-person-last-name': 'Lovelace', 'dg-person-email': 'ada@example.com',
           'dg-person-phone-number': None},
    )

    assert to_legacy_person(document, [SECURITY]) == {
        'public_id': ADA,
        'display_name': 'Ada Lovelace',
        'first_name': 'Ada',
        'last_name': 'Lovelace',
        'phone_number': '',
        'email': 'ada@example.com',
        'groups': [SECURITY],
    }


def test_to_legacy_person_group() -> None:
    """The former management.personGroup shape"""
    document = group_object(SECURITY, 'Security', [ADA, BOB], email='sec@example.com')

    assert to_legacy_person_group(document) == {
        'public_id': SECURITY,
        'name': 'Security',
        'email': 'sec@example.com',
        'group_members': [ADA, BOB],
    }


def test_to_legacy_person_group_without_email() -> None:
    """A null email reads as ''"""
    document = group_object(SECURITY, 'Security')
    document['fields'][1]['value'] = None

    assert to_legacy_person_group(document)['email'] == ''


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  person_lookup_stage                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_person_lookup_stage_joins_the_object_collection_by_public_id() -> None:
    """The ISMS reports read display_name / name of the joined document, as with the old collections"""
    stage: dict[str, Any] = person_lookup_stage('risk_owner_id', 'risk_owner')
    lookup: dict[str, Any] = stage['$lookup']

    assert lookup['from'] == 'framework.objects'
    assert lookup['localField'] == 'risk_owner_id'
    assert lookup['foreignField'] == 'public_id'
    assert lookup['as'] == 'risk_owner'

    projection: dict[str, Any] = lookup['pipeline'][0]['$project']

    assert set(projection) == {'_id', 'public_id', 'display_name', 'name'}
    assert 'dg-person-display-name' in repr(projection['display_name'])
    assert 'dg-person-group-name' in repr(projection['name'])
