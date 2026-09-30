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
What a `PUT /types/<id>` does to the Objects of that Type

A Type update carries its field changes into every Object of the Type, in two places: the flat
`fields` list (every field, MDS ones included) and, for a multi-data section, every captured row. Both
run as server-side statements, so what is pinned here is the outcome over HTTP:

* a new field reaches every Object - its flat entry and every row of its section - with the type and
  the default `value` the Type declares
* a removed field leaves both places, and a removed section leaves the Objects
* an entry an Object carries for a field the Type does not declare is dropped
* saving the same Type again changes nothing, and a label-only edit touches no Object

**The payload is round-tripped, never hand-built**: the stored Type is read through `GET /types/<id>`
and only the part under test is changed, so the request is schema-valid by construction.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/types'
UPDATE_ACCEPTED: tuple[HTTPStatus, ...] = (HTTPStatus.OK, HTTPStatus.ACCEPTED)

TYPE_ID: int = 9870
OBJECT_ID: int = 9880
OTHER_TYPE_OBJECT_ID: int = 9881

FLAT_FIELD: str = 'dg-prop-hostname'
MDS_SECTION: str = 'dg-prop-interfaces'
MDS_FIELD: str = 'dg-prop-ip'
NEW_MDS_FIELD: str = 'dg-prop-vlan'
NEW_FLAT_FIELD: str = 'dg-prop-owner'
STALE_FIELD: str = 'dg-prop-stale'

FLAT_VALUE: str = 'srv-prop-01'
ROW_VALUE: str = '10.0.0.1'
VLAN_DEFAULT: str = 'vlan-100'
OWNER_DEFAULT: str = 'ops'


def _type_doc() -> dict[str, Any]:
    """A CmdbType with one ordinary field and one multi-data section holding one field."""
    return {
        'public_id': TYPE_ID,
        'name': 'propagation_type',
        'label': 'Propagation',
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'version': '1.0.0',
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [
            {'type': 'text', 'name': FLAT_FIELD, 'label': 'Hostname'},
            {'type': 'text', 'name': MDS_FIELD, 'label': 'IP'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'externals': [],
            'sections': [
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [FLAT_FIELD]},
                {'type': 'multi-data-section', 'name': MDS_SECTION, 'label': 'Interfaces', 'fields': [MDS_FIELD]},
            ],
            'summary': {'fields': [FLAT_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int, type_id: int = TYPE_ID) -> dict[str, Any]:
    """An Object holding a flat value for each field and one MDS row."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [
            {'name': FLAT_FIELD, 'value': FLAT_VALUE, 'type': 'text'},
            {'name': MDS_FIELD, 'value': None, 'type': 'text'},
        ],
        'multi_data_sections': [{
            'section_id': MDS_SECTION,
            'highest_id': 1,
            'values': [{'multi_data_id': 1, 'data': [{'name': MDS_FIELD, 'value': ROW_VALUE, 'type': 'text'}]}],
        }],
    }


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds the Type, one Object of it, and one Object of ANOTHER type with the same shape

    The other Object shows a statement is scoped to the Type. Yields the objects collection.
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': [OBJECT_ID, OTHER_TYPE_OBJECT_ID]}})

    _purge()
    types.insert_one(_type_doc())
    objects.insert_many([_object_doc(OBJECT_ID), _object_doc(OTHER_TYPE_OBJECT_ID, type_id=TYPE_ID + 1)])

    yield objects

    _purge()


def _read_back(rest_api) -> dict[str, Any]:
    """The stored Type as the route hands it out - the only schema-valid starting point for a PUT."""
    return rest_api.get(f'{ROUTE_URL}/{TYPE_ID}').get_json()['result']


def _put(rest_api, payload: dict[str, Any]) -> None:
    """Saves the Type and asserts the update was accepted."""
    response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

    assert response.status_code in UPDATE_ACCEPTED, response.get_json()


def _stored(objects, public_id: int = OBJECT_ID) -> dict[str, Any]:
    """One Object as stored."""
    return objects.find_one({'public_id': public_id}, {'_id': 0})


def _flat(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The flat entries of an Object, by field name."""
    return {entry['name']: entry for entry in document['fields']}


def _row(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The entries of the Object's first MDS row, by field name."""
    return {entry['name']: entry for entry in document['multi_data_sections'][0]['values'][0]['data']}


def _with_new_mds_field(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with NEW_MDS_FIELD declared - a `date` with a default - and added to the MDS section."""
    payload['fields'].append({'type': 'date', 'name': NEW_MDS_FIELD, 'label': 'VLAN', 'value': VLAN_DEFAULT})
    payload['render_meta']['sections'][1]['fields'].append(NEW_MDS_FIELD)

    return payload


class TestAddingAField:
    """A new field reaches every Object of the Type, with what the Type declares for it."""

    def test_a_new_mds_field_reaches_every_row_with_its_type_and_default(self, rest_api, objects) -> None:
        """The row entry is built from the updated Type's declaration"""
        _put(rest_api, _with_new_mds_field(_read_back(rest_api)))

        assert _row(_stored(objects))[NEW_MDS_FIELD] == {'name': NEW_MDS_FIELD, 'type': 'date', 'value': VLAN_DEFAULT}

    def test_a_new_mds_field_reaches_the_flat_list_too(self, rest_api, objects) -> None:
        """The flat list is the canonical field list, MDS fields included"""
        _put(rest_api, _with_new_mds_field(_read_back(rest_api)))

        assert _flat(_stored(objects))[NEW_MDS_FIELD]['value'] == VLAN_DEFAULT

    def test_existing_values_are_kept(self, rest_api, objects) -> None:
        """Adding a field touches nothing an Object already holds"""
        _put(rest_api, _with_new_mds_field(_read_back(rest_api)))

        stored = _stored(objects)
        assert _row(stored)[MDS_FIELD]['value'] == ROW_VALUE
        assert _flat(stored)[FLAT_FIELD]['value'] == FLAT_VALUE

    def test_a_new_flat_field_reaches_every_object_with_its_default(self, rest_api, objects) -> None:
        """An ordinary field starts from its declared default"""
        payload = _read_back(rest_api)
        payload['fields'].append({'type': 'text', 'name': NEW_FLAT_FIELD, 'label': 'Owner', 'value': OWNER_DEFAULT})
        payload['render_meta']['sections'][0]['fields'].append(NEW_FLAT_FIELD)

        _put(rest_api, payload)

        assert _flat(_stored(objects))[NEW_FLAT_FIELD] == {
            'name': NEW_FLAT_FIELD, 'type': 'text', 'value': OWNER_DEFAULT,
        }

    def test_an_object_of_another_type_is_not_touched(self, rest_api, objects) -> None:
        """Every statement is scoped to the updated Type"""
        before = _stored(objects, OTHER_TYPE_OBJECT_ID)

        _put(rest_api, _with_new_mds_field(_read_back(rest_api)))

        assert _stored(objects, OTHER_TYPE_OBJECT_ID) == before


class TestRemovingAFieldOrSection:
    """What the Type stops declaring, the Objects stop carrying."""

    def test_a_removed_mds_field_leaves_the_rows_and_the_flat_list(self, rest_api, objects) -> None:
        """Both places lose it"""
        payload = _read_back(rest_api)
        payload['fields'] = [field for field in payload['fields'] if field['name'] != MDS_FIELD]
        payload['render_meta']['sections'][1]['fields'] = []

        _put(rest_api, payload)

        stored = _stored(objects)
        assert MDS_FIELD not in _row(stored)
        assert MDS_FIELD not in _flat(stored)

    def test_a_removed_section_leaves_the_objects(self, rest_api, objects) -> None:
        """The Object stops carrying rows of a section its Type does not have"""
        payload = _read_back(rest_api)
        payload['fields'] = [field for field in payload['fields'] if field['name'] != MDS_FIELD]
        payload['render_meta']['sections'] = payload['render_meta']['sections'][:1]

        _put(rest_api, payload)

        assert _stored(objects)['multi_data_sections'] == []

    def test_an_undeclared_flat_entry_is_dropped(self, rest_api, objects) -> None:
        """An entry for a field the Type never declared goes with the next field-set change"""
        objects.update_one({'public_id': OBJECT_ID}, {'$push': {'fields': {'name': STALE_FIELD, 'value': 'x'}}})

        _put(rest_api, _with_new_mds_field(_read_back(rest_api)))

        assert STALE_FIELD not in _flat(_stored(objects))


class TestRepeatedAndMetadataEdits:
    """What does not change the field set changes no Object."""

    def test_saving_the_same_type_again_changes_nothing(self, rest_api, objects) -> None:
        """Every statement is idempotent, so a second identical save is a no-op on the Objects"""
        _put(rest_api, _with_new_mds_field(_read_back(rest_api)))
        after_first = _stored(objects)

        _put(rest_api, _read_back(rest_api))

        assert _stored(objects) == after_first

    def test_a_label_only_edit_touches_no_object(self, rest_api, objects) -> None:
        """A pure metadata edit issues no statement at all"""
        before = _stored(objects)
        payload = _read_back(rest_api)
        payload['label'] = 'Propagation (renamed label)'

        _put(rest_api, payload)

        assert _stored(objects) == before

