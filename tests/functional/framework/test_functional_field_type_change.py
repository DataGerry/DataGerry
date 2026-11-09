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
Functional tests: an object field's `type` is the type's, and a field that changes its type loses its values

The bug report: a type field changed from text to Select (in the UI: deleted and dropped again as a Select under the
same identifier, in one save) kept `"type": "text"` on every object in `GET /objects/` and `GET /objects/native/<id>`,
while `GET /objects/<id>` said `select` - and saving the object did not correct it. Pinned over HTTP:

  - a `PUT /types/<id>` that changes a field's type resets that field on every object - flat and in every MDS row -
    to the field's default value (or null), with the new type; every read answers the same type
  - a field whose type did not change keeps its values; saving the type again changes nothing
  - an object write stores the declared type, whatever `type` the body sent (PUT and PATCH)
  - a field that became a select takes an unknown value as a new option on the next save, like any select

The Type and its objects are the propagation tests' (`test_functional_type_update_propagation`)
"""
from http import HTTPStatus
from typing import Any

from tests.functional.framework import test_functional_type_update_propagation as propagation
from tests.functional.framework.test_functional_type_update_propagation import (
    FLAT_FIELD,
    FLAT_VALUE,
    MDS_FIELD,
    OBJECT_ID,
    ROW_VALUE,
    _flat,
    _put,
    _read_back,
    _row,
    _stored,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
SELECT: str = 'select'
DATE: str = 'date'
TEXT: str = 'text'
FLAT_DEFAULT: str = 'running'
OPTIONS: list[dict[str, str]] = [{'name': FLAT_DEFAULT, 'label': 'Running'}, {'name': 'stopped', 'label': 'Stopped'}]
NEW_OPTION: str = 'retired'

# The seeded Type and its object: the propagation tests' fixture, registered here under its name
fixture_objects = propagation.fixture_objects


def _change_types(rest_api: Any, flat_type: str, mds_type: str | None = None) -> None:
    """PUTs the Type with FLAT_FIELD as `flat_type` (default FLAT_DEFAULT) and MDS_FIELD as `mds_type`."""
    payload: dict[str, Any] = _read_back(rest_api)

    for field in payload['fields']:
        if field['name'] == FLAT_FIELD:
            field.update({'type': flat_type, 'value': FLAT_DEFAULT, 'options': OPTIONS})
        elif field['name'] == MDS_FIELD and mds_type is not None:
            field['type'] = mds_type

    _put(rest_api, payload)


def _native(rest_api: Any) -> dict[str, Any]:
    """GET /objects/native/<id>"""
    return rest_api.get(f'{OBJECTS_URL}/native/{OBJECT_ID}').get_json()


def _listed(rest_api: Any) -> dict[str, Any]:
    """The object as GET /objects/ lists it"""
    response = rest_api.get(f'{OBJECTS_URL}/', query_string={'filter': '{"public_id": %d}' % OBJECT_ID})

    return response.get_json()['results'][0]


def _rendered_type(rest_api: Any, name: str) -> str:
    """The type GET /objects/<id> renders a field with"""
    rendered = rest_api.get(f'{OBJECTS_URL}/{OBJECT_ID}').get_json()

    return next(field['type'] for field in rendered['fields'] if field['name'] == name)


class TestATypeChangeResetsTheField:
    """The reported case, and what the ruling made of it"""

    def test_every_read_answers_the_new_type(self, rest_api, objects) -> None:
        """List, native and rendered agree - the report's two answers are one"""
        _change_types(rest_api, SELECT)

        assert _flat(_native(rest_api))[FLAT_FIELD]['type'] == SELECT
        assert _flat(_listed(rest_api))[FLAT_FIELD]['type'] == SELECT
        assert _rendered_type(rest_api, FLAT_FIELD) == SELECT

    def test_the_value_becomes_the_fields_default(self, rest_api, objects) -> None:
        """The old text is no option of the select: the field takes its declared default"""
        _change_types(rest_api, SELECT)

        assert _flat(_stored(objects))[FLAT_FIELD] == {'name': FLAT_FIELD, 'value': FLAT_DEFAULT, 'type': SELECT}

    def test_an_mds_field_without_a_default_is_cleared_in_every_row(self, rest_api, objects) -> None:
        """The row entry and the flat entry of the MDS field: null, typed date"""
        _change_types(rest_api, TEXT, mds_type=DATE)

        stored = _stored(objects)
        assert _row(stored)[MDS_FIELD] == {'name': MDS_FIELD, 'value': None, 'type': DATE}
        assert _flat(stored)[MDS_FIELD] == {'name': MDS_FIELD, 'value': None, 'type': DATE}

    def test_a_field_that_kept_its_type_keeps_its_values(self, rest_api, objects) -> None:
        """Only the changed field is reset: the MDS row keeps its value"""
        _change_types(rest_api, SELECT)

        assert _row(_stored(objects))[MDS_FIELD] == {'name': MDS_FIELD, 'value': ROW_VALUE, 'type': TEXT}

    def test_saving_the_type_again_changes_nothing(self, rest_api, objects) -> None:
        """Once reset, the object holds the declared type - a second save resets nothing a user set since"""
        _change_types(rest_api, SELECT)
        objects.update_one({'public_id': OBJECT_ID, 'fields.name': FLAT_FIELD}, {'$set': {'fields.$.value': 'stopped'}})

        _put(rest_api, _read_back(rest_api))

        assert _flat(_stored(objects))[FLAT_FIELD]['value'] == 'stopped'


class TestAnObjectWriteStoresTheDeclaredType:
    """The entry's type is the server's: a body cannot store another one"""

    def test_put_overwrites_a_sent_type(self, rest_api, objects) -> None:
        """A text field sent as `date` is stored as `text`, its value as sent"""
        native = _native(rest_api)
        body = {key: native[key] for key in ('type_id', 'fields', 'multi_data_sections', 'active')}
        body['fields'] = [{**field, 'type': DATE} for field in body['fields']]

        response = rest_api.put(f'{OBJECTS_URL}/{OBJECT_ID}', json=body)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _flat(_stored(objects))[FLAT_FIELD] == {'name': FLAT_FIELD, 'value': FLAT_VALUE, 'type': TEXT}

    def test_patch_overwrites_a_sent_type(self, rest_api, objects) -> None:
        """The partial update runs the same stamp"""
        response = rest_api.patch(f'{OBJECTS_URL}/{OBJECT_ID}', json={
            'fields': [{'name': FLAT_FIELD, 'value': 'patched', 'type': DATE}],
        })

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _flat(_stored(objects))[FLAT_FIELD] == {'name': FLAT_FIELD, 'value': 'patched', 'type': TEXT}

    def test_a_stale_entry_is_corrected_by_the_next_save(self, rest_api, objects) -> None:
        """An entry stored with a wrong type before (the reported data) is stamped when the object is saved"""
        objects.update_one({'public_id': OBJECT_ID, 'fields.name': FLAT_FIELD}, {'$set': {'fields.$.type': DATE}})

        rest_api.patch(f'{OBJECTS_URL}/{OBJECT_ID}', json={'fields': [{'name': FLAT_FIELD, 'value': FLAT_VALUE}]})

        assert _flat(_stored(objects))[FLAT_FIELD]['type'] == TEXT


def test_a_field_that_became_a_select_learns_a_new_option_on_save(rest_api, objects) -> None:
    """
    The select option sync reads the entry's type - with the stale `text` it skipped the field

    A value the select does not offer becomes an option of the type, as on every other select field
    """
    _change_types(rest_api, SELECT)

    response = rest_api.patch(f'{OBJECTS_URL}/{OBJECT_ID}',
                              json={'fields': [{'name': FLAT_FIELD, 'value': NEW_OPTION}]})

    assert response.status_code == HTTPStatus.ACCEPTED
    field = next(field for field in _read_back(rest_api)['fields'] if field['name'] == FLAT_FIELD)
    assert NEW_OPTION in [option['name'] for option in field['options']]
