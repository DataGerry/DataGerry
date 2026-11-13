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
Integration tests for the person selector on CmdbObjects against a real MongoDB

Seeds a person type, a group type, a hidden person type and an owning type whose ``owner`` (one, required) and
``members`` (several, required) selectors hold them - flat and in multi-data rows. Asserts:

  - the delete scrub lets every selector go of a deleted id, flat and in rows, leaves other values and other objects
    alone, and a second run changes nothing
  - the required-selection blocker finds an object whose required selector holds only deleted objects (flat or in a
    row), not one that keeps another selection, and never an object of the deletion itself
  - the picker browses active objects of the visible marked types, searches labels case-insensitively and literally,
    and resolves ids of inactive objects too
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.person_selector.selector_delete import find_required_selector_blockers, scrub_person_selectors
from cmdb.framework.person_selector.selector_picker import PickerQuery, find_person_choices
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE: int = 48301
GROUP_TYPE: int = 48302
HIDDEN_TYPE: int = 48303
OWNING_TYPE: int = 48304
TYPE_IDS: list[int] = [PERSON_TYPE, GROUP_TYPE, HIDDEN_TYPE, OWNING_TYPE]

ADA: int = 48311
BOB: int = 48312
OPS: int = 48313
EVE: int = 48314
GONE_AWAY: int = 48315
FLAT_ONLY_ADA: int = 48321
FLAT_ADA_AND_BOB: int = 48322
ROW_ONLY_ADA: int = 48323
OBJECT_IDS: list[int] = [ADA, BOB, OPS, EVE, GONE_AWAY, FLAT_ONLY_ADA, FLAT_ADA_AND_BOB, ROW_ONLY_ADA]

OWNER: str = 'owner'
MEMBERS: str = 'members'
SECTION: str = 'contacts'


def _selector(name: str, multiple: bool) -> dict[str, Any]:
    """A required selector"""
    return {'type': 'person', 'name': name, 'label': name, 'selectable': ['PERSON', 'PERSON_GROUP'],
            'multiple': multiple, 'required': True}


def _labelled(public_id: int, type_id: int, label_field: str, label: str, active: bool = True) -> dict[str, Any]:
    """A person or group object"""
    return {'public_id': public_id, 'type_id': type_id, 'active': active,
            'fields': [{'name': label_field, 'type': 'text', 'value': label}]}


def _owning(public_id: int, owner: Any, members: list[int], rows: list[list[int]]) -> dict[str, Any]:
    """An owning object"""
    return {'public_id': public_id, 'type_id': OWNING_TYPE, 'active': True,
            'fields': [{'name': OWNER, 'type': 'person', 'value': owner},
                       {'name': MEMBERS, 'type': 'person', 'value': members},
                       {'name': 'note', 'type': 'text', 'value': ADA}],
            'multi_data_sections': [{'section_id': SECTION, 'highest_id': len(rows), 'values': [
                {'multi_data_id': index, 'data': [{'name': MEMBERS, 'type': 'person', 'value': row}]}
                for index, row in enumerate(rows)
            ]}]}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The types and objects, purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_many([
        {'public_id': PERSON_TYPE, 'name': 'it-person', 'label': 'Person', 'special_type': 'PERSON', 'fields': []},
        {'public_id': GROUP_TYPE, 'name': 'it-group', 'label': 'Team', 'special_type': 'PERSON_GROUP', 'fields': []},
        {'public_id': HIDDEN_TYPE, 'name': 'it-hidden', 'label': 'Secret', 'special_type': 'PERSON', 'fields': []},
        {'public_id': OWNING_TYPE, 'name': 'it-owning', 'label': 'Owning', 'special_type': '',
         'fields': [_selector(OWNER, False), _selector(MEMBERS, True), {'type': 'text', 'name': 'note'}]},
    ])
    objects.insert_many([
        _labelled(ADA, PERSON_TYPE, 'display_name', 'Ada Lovelace'),
        _labelled(BOB, PERSON_TYPE, 'display_name', 'Bob (ops)'),
        _labelled(GONE_AWAY, PERSON_TYPE, 'display_name', 'Gone Away', active=False),
        _labelled(OPS, GROUP_TYPE, 'name', 'Operations'),
        _labelled(EVE, HIDDEN_TYPE, 'display_name', 'Eve'),
        _owning(FLAT_ONLY_ADA, ADA, [ADA], [[BOB]]),
        _owning(FLAT_ADA_AND_BOB, BOB, [ADA, BOB], [[ADA, OPS]]),
        _owning(ROW_ONLY_ADA, BOB, [BOB], [[ADA]]),
    ])
    yield objects
    _purge()


def _managers(database_manager: MongoDatabaseManager) -> tuple[ObjectsManager, TypesManager]:
    """Real managers on the test database"""
    return ObjectsManager(database_manager), TypesManager(database_manager)


def _values(objects: Any, public_id: int) -> tuple[Any, Any, list[Any], Any]:
    """owner, members, the row values, the untouched note"""
    document: dict[str, Any] = objects.find_one({'public_id': public_id})
    flat: dict[str, Any] = {entry['name']: entry['value'] for entry in document['fields']}

    rows: list[Any] = [row['data'][0]['value'] for row in document['multi_data_sections'][0]['values']]

    return (flat[OWNER], flat[MEMBERS], rows,
            flat['note'])


def test_the_scrub_lets_every_selector_go_of_the_deleted_id(seeded: Any,
                                                             database_manager: MongoDatabaseManager) -> None:
    """Flat and in rows; a text field holding the same number is no selection"""
    scrub_person_selectors(*_managers(database_manager), [ADA])

    assert _values(seeded, FLAT_ONLY_ADA) == (None, [], [[BOB]], ADA)
    assert _values(seeded, FLAT_ADA_AND_BOB) == (BOB, [BOB], [[OPS]], ADA)
    assert _values(seeded, ROW_ONLY_ADA) == (BOB, [BOB], [[]], ADA)


def test_a_second_scrub_changes_nothing(seeded: Any, database_manager: MongoDatabaseManager) -> None:
    """State-based"""
    scrub_person_selectors(*_managers(database_manager), [ADA])
    first: list[dict[str, Any]] = list(seeded.find({'public_id': {'$in': OBJECT_IDS}}, {'_id': 0}).sort('public_id', 1))

    scrub_person_selectors(*_managers(database_manager), [ADA])

    assert list(seeded.find({'public_id': {'$in': OBJECT_IDS}}, {'_id': 0}).sort('public_id', 1)) == first


@pytest.mark.usefixtures('seeded')
def test_the_blockers_hold_only_deleted_objects_in_a_required_selector(database_manager: MongoDatabaseManager) -> None:
    """Flat owner and members only Ada; a row only Ada - not the object keeping Bob everywhere"""
    blockers = find_required_selector_blockers(*_managers(database_manager), [ADA])

    assert blockers == [(FLAT_ONLY_ADA, OWNING_TYPE), (ROW_ONLY_ADA, OWNING_TYPE)]


@pytest.mark.usefixtures('seeded')
def test_an_object_of_the_deletion_is_no_blocker(database_manager: MongoDatabaseManager) -> None:
    """It goes too"""
    blockers = find_required_selector_blockers(*_managers(database_manager), [ADA, FLAT_ONLY_ADA, ROW_ONLY_ADA])

    assert blockers == []


@pytest.mark.usefixtures('seeded')
def test_deleting_every_selection_blocks(database_manager: MongoDatabaseManager) -> None:
    """Members Ada and Bob both deleted"""
    blockers = find_required_selector_blockers(*_managers(database_manager), [ADA, BOB])

    assert [object_id for object_id, _ in blockers] == [FLAT_ONLY_ADA, FLAT_ADA_AND_BOB, ROW_ONLY_ADA]


def _labels(database_manager: MongoDatabaseManager, query: PickerQuery) -> tuple[list[Any], int]:
    """The picker's labels and total, the hidden type denied"""
    results, total = find_person_choices(*_managers(database_manager), lambda: frozenset({HIDDEN_TYPE}), query)

    return [result['label'] for result in results], total


@pytest.mark.usefixtures('seeded')
def test_the_picker_browses_active_visible_persons_and_groups(database_manager: MongoDatabaseManager) -> None:
    """Not the inactive person, not the hidden type's"""
    kinds = [SpecialType.PERSON, SpecialType.PERSON_GROUP]

    assert _labels(database_manager, PickerQuery(kinds, None, None, 1, 25)) == (
        ['Ada Lovelace', 'Bob (ops)', 'Operations'], 3)


@pytest.mark.usefixtures('seeded')
def test_the_picker_search_is_literal_and_case_insensitive(database_manager: MongoDatabaseManager) -> None:
    """'(OPS)' matches Bob's label only - the brackets are text; each kind by its own label field"""
    kinds = [SpecialType.PERSON, SpecialType.PERSON_GROUP]

    assert _labels(database_manager, PickerQuery(kinds, '(OPS)', None, 1, 25)) == (['Bob (ops)'], 1)
    assert _labels(database_manager, PickerQuery(kinds, 'OP', None, 1, 25)) == (['Bob (ops)', 'Operations'], 2)


@pytest.mark.usefixtures('seeded')
def test_the_picker_resolves_ids_of_inactive_objects(database_manager: MongoDatabaseManager) -> None:
    """A hidden one is not answered"""
    query = PickerQuery([SpecialType.PERSON], None, [GONE_AWAY, EVE], 1, 25)

    assert _labels(database_manager, query) == (['Gone Away'], 1)
