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
Functional tests: an object write holds its field names and multi-data sections to the structure rule

Through the real routes, against a type with two multi-data sections. Pinned per break - a section sent twice, an
undeclared section, a section without an id, a row carrying a field its section does not declare, a row without an
id, a row id two rows share, a field name twice (top level and in a row), a part that is no object or no list - on
POST and PUT: one 400 naming the reason, nothing stored or changed (each of them used to be stored, the malformed
parts were a 500). The controls: row id 0 is legal; the row-id counter is aligned - never below a row id, never back
below the stored one. PATCH: a stale stored counter no longer hands out an id a row holds, so a delete by that id
removes one row, not two
"""
import copy
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.framework.object_section_structure_constants import (
    ENTRY_INVALID,
    FIELDS_REPEATED,
    MIN_ROW_ID,
    OBJECT_STRUCTURE_INVALID_MSG,
    ROW_DATA_NOT_A_LIST,
    ROW_FIELDS_REPEATED,
    ROW_FIELDS_UNDECLARED,
    ROW_ID_INVALID,
    ROW_IDS_REPEATED,
    SECTION_NOT_AN_OBJECT,
    SECTION_REPEATED,
    SECTION_UNDECLARED,
    SECTION_WITHOUT_ID,
    VALUES_NOT_A_LIST,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'
TYPE_ID: int = 97361
STORED_ID: int = 97362
CREATED_IDS: list[int] = [97363, 97364]
SEEDED_IDS: list[int] = [STORED_ID, *CREATED_IDS]
HOST: str = 'host'
NICS: str = 'nics'
NIC: str = 'nic'
DISKS: str = 'disks'
SIZE: str = 'size'
STORED_COUNTER: int = 9


def _type_doc() -> dict[str, Any]:
    """A type with a host field and two multi-data sections"""
    return {
        'public_id': TYPE_ID, 'name': f'structure-type-{TYPE_ID}', 'label': 'Structure', 'author_id': 1,
        'active': True, 'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
        'fields': [{'type': 'text', 'name': name, 'label': name} for name in (HOST, NIC, SIZE)],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': [HOST]}, 'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [HOST]},
            {'type': 'multi-data-section', 'name': NICS, 'label': 'Nics', 'fields': [NIC]},
            {'type': 'multi-data-section', 'name': DISKS, 'label': 'Disks', 'fields': [SIZE]},
        ]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _row(row_id: Any, *names: str) -> dict[str, Any]:
    """A row naming the given fields"""
    return {'multi_data_id': row_id, 'data': [{'name': name, 'value': f'{name}-{row_id}'} for name in names]}


def _body(*sections: Any, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An object of the type"""
    return {'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': fields or [{'name': HOST, 'value': 'h'}], 'multi_data_sections': list(sections)}


def _nics(*rows: Any, highest_id: int | None = None) -> dict[str, Any]:
    """The nics section"""
    section: dict[str, Any] = {'section_id': NICS, 'values': list(rows)}

    if highest_id is not None:
        section['highest_id'] = highest_id

    return section


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The type and one stored object (nics row 1, counter STORED_COUNTER); removed afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'type_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': SEEDED_IDS}})

    _purge()
    types.insert_one(_type_doc())
    objects.insert_one({**_body(_nics(_row(1, NIC), highest_id=STORED_COUNTER)), 'public_id': STORED_ID,
                        'creation_time': datetime.now(timezone.utc)})

    yield objects

    _purge()


def _refusal(*reasons: str) -> str:
    """The 400's message"""
    return OBJECT_STRUCTURE_INVALID_MSG.format(reasons='; '.join(reasons))


BREAKS: dict[str, tuple[dict[str, Any], str]] = {
    'section-twice': (_body(_nics(_row(1, NIC)), _nics(_row(2, NIC))), SECTION_REPEATED.format(section_id=NICS)),
    'undeclared-section': (_body({'section_id': 'ghosts', 'values': []}),
                           SECTION_UNDECLARED.format(section_id='ghosts')),
    'section-without-id': (_body({'values': [_row(1, NIC)]}), SECTION_WITHOUT_ID.format(position=0)),
    'field-outside-section': (_body(_nics(_row(1, NIC, SIZE))),
                              ROW_FIELDS_UNDECLARED.format(section_id=NICS, position=0, names=[SIZE])),
    'top-level-field-in-row': (_body(_nics(_row(1, HOST))),
                               ROW_FIELDS_UNDECLARED.format(section_id=NICS, position=0, names=[HOST])),
    'row-without-id': (_body(_nics({'data': [{'name': NIC, 'value': 'x'}]})),
                       ROW_ID_INVALID.format(section_id=NICS, position=0, minimum=MIN_ROW_ID)),
    'negative-row-id': (_body(_nics(_row(-1, NIC))),
                        ROW_ID_INVALID.format(section_id=NICS, position=0, minimum=MIN_ROW_ID)),
    'shared-row-id': (_body(_nics(_row(2, NIC), _row(2, NIC))), ROW_IDS_REPEATED.format(section_id=NICS, row_ids=[2])),
    'field-twice-top-level': (_body(fields=[{'name': HOST, 'value': 'a'}, {'name': HOST, 'value': 'b'}]),
                              FIELDS_REPEATED.format(names=[HOST])),
    'field-twice-in-row': (_body(_nics(_row(1, NIC, NIC))),
                           ROW_FIELDS_REPEATED.format(section_id=NICS, position=0, names=[NIC])),
    'section-no-object': (_body('oops'), SECTION_NOT_AN_OBJECT.format(position=0)),
    'values-no-list': (_body({'section_id': NICS, 'values': 'x'}), VALUES_NOT_A_LIST.format(section_id=NICS)),
    'data-no-list': (_body(_nics({'multi_data_id': 1, 'data': 'x'})),
                     ROW_DATA_NOT_A_LIST.format(section_id=NICS, position=0)),
    'entry-no-object': (_body(_nics({'multi_data_id': 1, 'data': ['x']})),
                        ENTRY_INVALID.format(section_id=NICS, position=0)),
}


@pytest.mark.parametrize('name', list(BREAKS))
def test_a_create_breaking_the_rule_is_one_400_and_stores_nothing(rest_api, objects: Any, name: str) -> None:
    """Each used to be stored (the malformed parts a 500)"""
    body, reason = BREAKS[name]

    response = rest_api.post(f'{ROUTE_URL}/', json=copy.deepcopy(body))

    assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _refusal(reason))
    assert objects.count_documents({'type_id': TYPE_ID}) == 1


@pytest.mark.parametrize('name', list(BREAKS))
def test_an_update_breaking_the_rule_is_one_400_and_changes_nothing(rest_api, objects: Any, name: str) -> None:
    """The stored object is untouched"""
    body, reason = BREAKS[name]
    before: dict[str, Any] = objects.find_one({'public_id': STORED_ID})

    response = rest_api.put(f'{ROUTE_URL}/{STORED_ID}', json=copy.deepcopy(body))

    assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _refusal(reason))
    assert objects.find_one({'public_id': STORED_ID}) == before


def test_every_reason_is_named_in_one_400(rest_api, objects: Any) -> None:
    """Not the first one only"""
    response = rest_api.post(f'{ROUTE_URL}/', json=_body(_nics(_row(1, NIC)), _nics(_row(1, NIC)), 'oops'))

    assert response.get_json()['message'] == _refusal(
        SECTION_REPEATED.format(section_id=NICS), SECTION_NOT_AN_OBJECT.format(position=2),
    )
    assert objects.count_documents({'type_id': TYPE_ID}) == 1


def test_a_create_with_row_id_zero_is_stored_with_its_counter(rest_api, objects: Any) -> None:
    """0 is an id; the counter is the largest row id, whatever was sent"""
    response = rest_api.post(f'{ROUTE_URL}/', json={
        **_body(_nics(_row(0, NIC), _row(3, NIC), highest_id=0), {'section_id': DISKS, 'values': [_row(0, SIZE)]}),
        'public_id': CREATED_IDS[0],
    })

    assert response.status_code == HTTPStatus.OK
    sections = objects.find_one({'public_id': CREATED_IDS[0]})['multi_data_sections']
    assert [(section['section_id'], section['highest_id']) for section in sections] == [(NICS, 3), (DISKS, 0)]


def test_an_update_never_moves_the_counter_back(rest_api, objects: Any) -> None:
    """A dropped top row's id is never handed out again"""
    response = rest_api.put(f'{ROUTE_URL}/{STORED_ID}', json=_body(_nics(_row(1, NIC), _row(2, NIC), highest_id=2)))

    assert response.status_code == HTTPStatus.ACCEPTED
    section = objects.find_one({'public_id': STORED_ID})['multi_data_sections'][0]
    assert (section['highest_id'], [row['multi_data_id'] for row in section['values']]) == (STORED_COUNTER, [1, 2])


def test_a_patch_row_never_takes_a_held_id_so_a_delete_takes_one_row(rest_api, objects: Any) -> None:
    """A stored counter below the rows (as stored objects hold): the new row goes above them"""
    objects.update_one({'public_id': STORED_ID}, {'$set': {'multi_data_sections': [
        _nics(_row(1, NIC), _row(2, NIC), highest_id=1),
    ]}})

    created = rest_api.patch(f'{ROUTE_URL}/{STORED_ID}', json={'created_mds_rows': [
        {'section_id': NICS, 'data': [{'name': NIC, 'value': 'new'}]},
    ]})
    deleted = rest_api.patch(f'{ROUTE_URL}/{STORED_ID}', json={'deleted_mds_rows': [
        {'section_id': NICS, 'multi_data_id': 2},
    ]})

    assert (created.status_code, deleted.status_code) == (HTTPStatus.ACCEPTED, HTTPStatus.ACCEPTED)
    section = objects.find_one({'public_id': STORED_ID})['multi_data_sections'][0]
    assert [(row['multi_data_id'], row['data'][0]['value']) for row in section['values']] == [
        (1, f'{NIC}-1'), (3, 'new'),
    ]
    assert section['highest_id'] == 3
