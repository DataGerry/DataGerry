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
A rendered object field entry is a name + value + type triple, whatever the object holds

The render fills every field the TYPE declares, so an object that carries no entry for one still
answers it. Answering with the type's field definition unchanged is the trap - a type field with
no configured default has no ``value`` key at all, so the entry reached the client without one:
`undefined` rather than null, for every field the object has no value for.

No stale data is needed to get there. A create that sends only some of the Type's fields leaves the
rest in exactly that state, which is what these tests drive.
"""
import uuid
from http import HTTPStatus
from typing import Any

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_URL: str = '/types/'
OBJECT_URL: str = '/objects/'

SUPPLIED_FIELD: str = 'text-hostname'
SUPPLIED_VALUE: str = 'srv-prod-01'
DEFAULTED_FIELD: str = 'text-with-default'
FIELD_DEFAULT: str = 'the-type-default'


def _field(name: str, label: str, field_type: str = 'text', **extra: Any) -> dict[str, Any]:
    """A type field definition, optionally carrying a configured default under 'value'."""
    return {'type': field_type, 'name': name, 'label': label, **extra}


@pytest.fixture(name='type_id')
def fixture_type_id(rest_api) -> int:
    """A Type whose fields cover the three cases: supplied, unsupplied, and carrying a default."""
    fields = [
        _field(SUPPLIED_FIELD, 'Hostname'),
        _field('text-serial', 'Serial'),
        _field('date-bought', 'Bought', 'date'),
        _field(DEFAULTED_FIELD, 'With default', value=FIELD_DEFAULT),
    ]
    created = rest_api.post(TYPE_URL, json={
        'author_id': 1,
        'name': f'render_contract_{uuid.uuid4().hex[:8]}',
        'label': 'Render Contract',
        'active': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa fa-cube',
            'sections': [{'type': 'section', 'name': 'section-a', 'label': 'A',
                          'fields': [field['name'] for field in fields]}],
            'externals': [],
            'summary': {'fields': []},
        },
    })
    assert created.status_code in (HTTPStatus.OK, HTTPStatus.CREATED), created.get_data(as_text=True)

    return created.get_json()['result_id']


@pytest.fixture(name='partial_object_id')
def fixture_partial_object_id(rest_api, type_id: int) -> int:
    """An object created with a value for ONE of the Type's four fields."""
    created = rest_api.post(OBJECT_URL, json={
        'type_id': type_id, 'version': '1.0.0', 'author_id': 1, 'active': True,
        'fields': [{'name': SUPPLIED_FIELD, 'value': SUPPLIED_VALUE}],
    })
    body = created.get_json()

    return body['result_id'] if isinstance(body, dict) and 'result_id' in body else body


def _rendered_fields(rest_api, object_id: int) -> list[dict[str, Any]]:
    """The rendered field entries of one object."""
    response = rest_api.get(f'{OBJECT_URL}{object_id}')
    assert response.status_code == HTTPStatus.OK

    return (response.get_json() or {}).get('fields', [])


def test_every_rendered_entry_carries_a_value_key(rest_api, partial_object_id: int) -> None:
    """The regression: three of the four entries must not arrive with no 'value' key at all"""
    entries = _rendered_fields(rest_api, partial_object_id)

    assert entries
    assert [entry['name'] for entry in entries if 'value' not in entry] == []


def test_an_unsupplied_field_reads_as_null(rest_api, partial_object_id: int) -> None:
    """None, not a missing key - a client reading `field.value` gets a value it can test"""
    entries = {entry['name']: entry for entry in _rendered_fields(rest_api, partial_object_id)}

    assert entries['text-serial']['value'] is None
    assert entries['date-bought']['value'] is None


def test_the_supplied_field_still_reads_its_value(rest_api, partial_object_id: int) -> None:
    """The fallback may not cost the ordinary case"""
    entries = {entry['name']: entry for entry in _rendered_fields(rest_api, partial_object_id)}

    assert entries[SUPPLIED_FIELD]['value'] == SUPPLIED_VALUE


def test_a_configured_type_default_still_reaches_the_reader(rest_api, partial_object_id: int) -> None:
    """The key is only established when absent, so a Type's default is not overwritten with None"""
    entries = {entry['name']: entry for entry in _rendered_fields(rest_api, partial_object_id)}

    assert entries[DEFAULTED_FIELD]['value'] == FIELD_DEFAULT
