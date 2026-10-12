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
Unit tests for cmdb.framework.person.enforcement

Pure tests with the in-memory managers of tests.utils.person_stubs. Pinned here is the person invariant of
the object write path:

  - every person value is canonicalised IN PLACE on the candidate, and its row type stamped 'person' - the
    delete cascade finds person values by that row type, so it must not depend on the client
  - the shape is judged first; the ids are resolved - one query for all of them - only when every value
    has a valid shape
  - an id must name an existing object of the SpecialType its 'ref_type' claims
  - an object whose type has no person field is not touched and costs no lookup
"""
from typing import Any

import pytest

from cmdb.utils import ValidationErrorKey
from cmdb.framework.person.enforcement import (
    ABORT_PREFIX,
    enforce_person_object_invariants,
    format_person_errors_for_abort,
)
from tests.utils.person_stubs import (
    StubObjectsManager,
    StubTypesManager,
    group_object,
    person_field,
    person_group_type_doc,
    person_object,
    person_type_doc,
    selection,
)
# -------------------------------------------------------------------------------------------------------------------- #

ASSET_TYPE_ID: int = 40
PLAIN_TYPE_ID: int = 41

ADA: int = 100
BOB: int = 101
SECURITY: int = 200
SERVER: int = 300

PERSON: str = 'PERSON'
GROUP: str = 'PERSON_GROUP'


def _asset_type() -> dict[str, Any]:
    """A type with a single owner (persons or groups), a multiple team (persons only) and a text field"""
    return {
        'public_id': ASSET_TYPE_ID,
        'name': 'asset',
        'label': 'Asset',
        'fields': [
            {'type': 'text', 'name': 'hostname', 'label': 'Hostname'},
            person_field('owner', 'Owner', ref_kind='BOTH', multiple=False),
            person_field('team', 'Team', ref_kind='PERSON', multiple=True),
        ],
    }


@pytest.fixture(name='managers')
def fixture_managers() -> tuple[StubObjectsManager, StubTypesManager]:
    """Two persons, one group and an ordinary object, plus the person types and two ordinary types"""
    objects_manager = StubObjectsManager([
        person_object(ADA, 'Ada Lovelace'),
        person_object(BOB, 'Bob'),
        group_object(SECURITY, 'Security', [ADA]),
        {'public_id': SERVER, 'type_id': PLAIN_TYPE_ID, 'fields': []},
    ])
    types_manager = StubTypesManager([
        person_type_doc(),
        person_group_type_doc(),
        _asset_type(),
        {'public_id': PLAIN_TYPE_ID, 'name': 'plain', 'label': 'Plain', 'fields': [{'type': 'text', 'name': 'x'}]},
    ])

    return objects_manager, types_manager


def _candidate(**values: Any) -> dict[str, Any]:
    return {
        'type_id': ASSET_TYPE_ID,
        'fields': [{'name': 'hostname', 'value': 'srv'}] + [{'name': name, 'value': value} for name, value in values.items()],
    }


def _field(candidate: dict[str, Any], name: str) -> dict[str, Any]:
    return next(entry for entry in candidate['fields'] if entry['name'] == name)


def _messages(errors: list[dict[str, Any]]) -> list[str]:
    return [error[ValidationErrorKey.MESSAGE] for error in errors]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    valid values                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_valid_single_and_multiple_value_passes(managers: Any) -> None:
    """A group as owner, two persons as team"""
    candidate = _candidate(owner=selection(GROUP, SECURITY), team=[selection(PERSON, ADA), selection(PERSON, BOB)])

    assert enforce_person_object_invariants(*managers, candidate) == []


def test_the_value_is_canonicalised_in_place(managers: Any) -> None:
    """A lone pair in a multiple field becomes a list, duplicates go, a one-entry list in a single field unwraps"""
    candidate = _candidate(
        owner=[selection(PERSON, ADA)],
        team=selection(PERSON, BOB),
    )

    assert enforce_person_object_invariants(*managers, candidate) == []
    assert _field(candidate, 'owner')['value'] == selection(PERSON, ADA)
    assert _field(candidate, 'team')['value'] == [selection(PERSON, BOB)]


@pytest.mark.parametrize('empty', [None, '', [], {}])
def test_the_empty_values_are_stored_canonically(managers: Any, empty: Any) -> None:
    """None for a single field, [] for a multiple one - and no lookup is needed"""
    objects_manager, types_manager = managers
    candidate = _candidate(owner=empty, team=empty)

    assert enforce_person_object_invariants(objects_manager, types_manager, candidate) == []
    assert _field(candidate, 'owner')['value'] is None
    assert _field(candidate, 'team')['value'] == []
    assert not objects_manager.find_calls


def test_the_row_type_is_stamped_on_every_person_entry(managers: Any) -> None:
    """The delete cascade matches person values by row type, so it is set whatever the client sent"""
    candidate = _candidate(owner=selection(PERSON, ADA), team=[])
    _field(candidate, 'owner')['type'] = 'text'

    enforce_person_object_invariants(*managers, candidate)

    assert _field(candidate, 'owner')['type'] == 'person'
    assert _field(candidate, 'team')['type'] == 'person'
    assert 'type' not in _field(candidate, 'hostname')


def test_a_person_field_in_a_multi_data_section_is_enforced(managers: Any) -> None:
    """An MDS row's person value is canonicalised, stamped and resolved like a top-level one"""
    row_entry: dict[str, Any] = {'name': 'team', 'value': selection(PERSON, ADA)}
    bad_entry: dict[str, Any] = {'name': 'team', 'value': [selection(PERSON, 999)]}
    candidate = {
        'type_id': ASSET_TYPE_ID,
        'fields': [],
        'multi_data_sections': [{'section_id': 'mds', 'values': [
            {'multi_data_id': 0, 'data': [row_entry]},
            {'multi_data_id': 1, 'data': [bad_entry]},
        ]}],
    }

    errors = enforce_person_object_invariants(*managers, candidate)

    assert row_entry == {'name': 'team', 'value': [selection(PERSON, ADA)], 'type': 'person'}
    assert _messages(errors) == ["The person field 'team' references PERSON 999, which does not exist"]


def test_all_ids_are_resolved_in_one_query(managers: Any) -> None:
    """However many fields and selections"""
    objects_manager, types_manager = managers
    candidate = _candidate(owner=selection(GROUP, SECURITY), team=[selection(PERSON, ADA), selection(PERSON, BOB)])

    enforce_person_object_invariants(objects_manager, types_manager, candidate)

    assert len(objects_manager.find_calls) == 1
    assert sorted(objects_manager.find_calls[0]['public_id']['$in']) == [ADA, BOB, SECURITY]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   refused values                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_kind_the_field_does_not_allow_is_refused_without_a_lookup(managers: Any) -> None:
    """The team only takes persons; the shape check refuses the group before anything is queried"""
    objects_manager, types_manager = managers
    candidate = _candidate(team=[selection(GROUP, SECURITY)])

    errors = enforce_person_object_invariants(objects_manager, types_manager, candidate)

    assert _messages(errors) == ["The person field 'team' does not allow 'PERSON_GROUP' (allowed: ['PERSON'])"]
    assert not objects_manager.find_calls


def test_an_unknown_id_is_refused(managers: Any) -> None:
    """An id naming no object"""
    errors = enforce_person_object_invariants(*managers, _candidate(owner=selection(PERSON, 999)))

    assert _messages(errors) == ["The person field 'owner' references PERSON 999, which does not exist"]


def test_an_id_of_the_wrong_kind_is_refused(managers: Any) -> None:
    """The group exists, but the selection claims it is a person"""
    errors = enforce_person_object_invariants(*managers, _candidate(owner=selection(PERSON, SECURITY)))

    assert _messages(errors) == [f"The person field 'owner' references PERSON {SECURITY}, which does not exist"]


def test_an_ordinary_object_is_no_person(managers: Any) -> None:
    """An existing object of a non-person type cannot be selected"""
    errors = enforce_person_object_invariants(*managers, _candidate(owner=selection(PERSON, SERVER)))

    assert len(errors) == 1


@pytest.mark.parametrize('value', [
    'Ada',
    [selection(PERSON, ADA), selection(PERSON, BOB)],
    {'ref_type': PERSON, 'id': ADA, 'label': 'Ada'},
    selection(PERSON, '100'),
])
def test_a_bad_shape_is_refused_without_a_lookup(managers: Any, value: Any) -> None:
    """Text, two selections in a single field, an extra key, a string id"""
    objects_manager, types_manager = managers

    errors = enforce_person_object_invariants(objects_manager, types_manager, _candidate(owner=value))

    assert len(errors) == 1
    assert not objects_manager.find_calls


def test_one_bad_shape_suppresses_the_lookup_of_the_valid_values(managers: Any) -> None:
    """The ids are only resolved once every value has a valid shape - the user fixes the shape first"""
    objects_manager, types_manager = managers
    candidate = _candidate(owner=selection(PERSON, 999), team='junk')

    errors = enforce_person_object_invariants(objects_manager, types_manager, candidate)

    assert _messages(errors) == ["The person field 'team' expects a list of selections"]
    assert not objects_manager.find_calls


def test_every_unknown_reference_is_reported(managers: Any) -> None:
    """One message per unresolved selection"""
    candidate = _candidate(owner=selection(GROUP, 998), team=[selection(PERSON, ADA), selection(PERSON, 999)])

    errors = enforce_person_object_invariants(*managers, candidate)

    assert _messages(errors) == [
        "The person field 'owner' references PERSON_GROUP 998, which does not exist",
        "The person field 'team' references PERSON 999, which does not exist",
    ]


def test_every_selection_is_unknown_while_the_person_types_do_not_exist() -> None:
    """Before an administrator created the types, no id can name a person"""
    objects_manager = StubObjectsManager([person_object(ADA, 'Ada')])
    types_manager = StubTypesManager([_asset_type()])

    errors = enforce_person_object_invariants(objects_manager, types_manager, _candidate(owner=selection(PERSON, ADA)))

    assert len(errors) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      no-ops                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_type_without_person_fields_is_not_touched(managers: Any) -> None:
    """No canonicalisation, no stamping, no query"""
    objects_manager, types_manager = managers
    candidate = {'type_id': PLAIN_TYPE_ID, 'fields': [{'name': 'x', 'value': ''}]}

    assert enforce_person_object_invariants(objects_manager, types_manager, candidate) == []
    assert candidate == {'type_id': PLAIN_TYPE_ID, 'fields': [{'name': 'x', 'value': ''}]}
    assert not objects_manager.find_calls


@pytest.mark.parametrize('type_id', [None, '40', 9999])
def test_a_candidate_without_a_known_type_is_left_to_the_other_checks(managers: Any, type_id: Any) -> None:
    """A missing, non-int or unknown type_id is not the person feature's business"""
    candidate = {'type_id': type_id, 'fields': [{'name': 'owner', 'value': 'junk'}]}

    assert enforce_person_object_invariants(*managers, candidate) == []


def test_a_person_field_the_candidate_omits_is_not_required(managers: Any) -> None:
    """Required-ness is the required-field check's business, not this one"""
    assert enforce_person_object_invariants(*managers, _candidate()) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    abort wording                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_format_person_errors_for_abort_joins_every_message() -> None:
    """One abort string naming the feature and every problem"""
    errors = [{ValidationErrorKey.MESSAGE.value: 'one'}, {ValidationErrorKey.MESSAGE.value: 'two'}]

    assert format_person_errors_for_abort(errors) == f'{ABORT_PREFIX}: one | two'
    assert ABORT_PREFIX == 'Person validation failed'
