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
Functional coverage of when a rendered reference carries its ``summaries``

The frontend's reference components show ``reference.summaries`` exactly when ``reference.line`` is
empty, and ``reference.line`` otherwise. So the pair is a contract, read through ``GET /objects/<id>``:

- **no nested summary line** (the default) - ``line`` is null and ``summaries`` hold the referenced
  type's summary fields; an empty list here would render the reference as a bare icon and label
- **a line with placeholders** - the filled ``line``, the summaries alongside
- **a line without placeholders** - the line as written, ``summaries`` empty: the line carries it all

A nested-summary entry missing one of its keys - as the type import stores it - renders with that key's
default instead of degrading to a bare icon and label, and one saved through the type route without
``fields`` is stored with an empty list.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_URL: str = '/objects'

TARGET_TYPE_ID: int = 93710
REFERRING_TYPE_ID: int = 93711
TARGET_OBJECT_ID: int = 93712
PLAIN_REFERRER_ID: int = 93713       # its reference field has no nested summary line
PLACEHOLDER_REFERRER_ID: int = 93714  # a nested line with a placeholder
STATIC_REFERRER_ID: int = 93715       # a nested line without placeholders
TYPE_IDS: list[int] = [TARGET_TYPE_ID, REFERRING_TYPE_ID]
OBJECT_IDS: list[int] = [TARGET_OBJECT_ID, PLAIN_REFERRER_ID, PLACEHOLDER_REFERRER_ID, STATIC_REFERRER_ID]

NAME_FIELD: str = 'target-name'
TARGET_NAME: str = 'core-switch-01'
PLAIN_REF_FIELD: str = 'ref-plain'
PLACEHOLDER_REF_FIELD: str = 'ref-placeholder'
STATIC_REF_FIELD: str = 'ref-static'
PLACEHOLDER_LINE: str = 'Device {}'
STATIC_LINE: str = 'See the rack plan'


def _type_doc(public_id: int, fields: list[dict[str, Any]], summary_fields: list[str]) -> dict[str, Any]:
    """A CmdbType with one plain section holding every field."""
    return {
        'public_id': public_id, 'name': f'reference-summaries-{public_id}', 'label': f'Reference {public_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'fields': fields,
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                          'fields': [field['name'] for field in fields]}],
            'summary': {'fields': summary_fields},
        },
        'acl': {'activated': False, 'groups': {'includes': None}}, 'version': '1.0.0',
    }


def _ref_field(name: str, line: str | None) -> dict[str, Any]:
    """A reference field to the target type, with a nested summary line when one is given."""
    field: dict[str, Any] = {'type': 'ref', 'name': name, 'label': name, 'ref_types': [TARGET_TYPE_ID]}

    if line is not None:
        # The entry as the type write schema describes it (label, icon and prefix included)
        field['summaries'] = [{
            'type_id': TARGET_TYPE_ID, 'line': line, 'label': name, 'fields': [NAME_FIELD],
            'icon': 'fa-cube', 'prefix': False,
        }]

    return field


def _object_doc(public_id: int, type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A stored CmdbObject."""
    return {
        'public_id': public_id, 'type_id': type_id, 'author_id': 1, 'active': True, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': fields, 'multi_data_sections': [],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the target type + object and one referring object per line case; removes all of it after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': TYPE_IDS}})
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    types.insert_many([
        _type_doc(TARGET_TYPE_ID, [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}], [NAME_FIELD]),
        _type_doc(REFERRING_TYPE_ID, [
            _ref_field(PLAIN_REF_FIELD, None),
            _ref_field(PLACEHOLDER_REF_FIELD, PLACEHOLDER_LINE),
            _ref_field(STATIC_REF_FIELD, STATIC_LINE),
        ], []),
    ])
    objects.insert_many([
        _object_doc(TARGET_OBJECT_ID, TARGET_TYPE_ID, [{'name': NAME_FIELD, 'value': TARGET_NAME}]),
        *[
            _object_doc(referrer, REFERRING_TYPE_ID, [{'name': field, 'value': TARGET_OBJECT_ID}])
            for referrer, field in ((PLAIN_REFERRER_ID, PLAIN_REF_FIELD),
                                    (PLACEHOLDER_REFERRER_ID, PLACEHOLDER_REF_FIELD),
                                    (STATIC_REFERRER_ID, STATIC_REF_FIELD))
        ],
    ])
    yield
    types.delete_many({'public_id': {'$in': TYPE_IDS}})
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})


def _reference(rest_api, object_id: int, field_name: str) -> dict[str, Any]:
    """The rendered reference payload of one field, as GET /objects/<id> answers it."""
    response = rest_api.get(f'{OBJECT_URL}/{object_id}')
    assert response.status_code == HTTPStatus.OK

    return next(field for field in response.get_json()['fields'] if field['name'] == field_name)['reference']


def _summary_values(reference: dict[str, Any]) -> list[str]:
    """The values the summaries carry, in order."""
    return [summary['value'] for summary in reference['summaries']]


def test_without_a_line_the_summaries_are_what_the_reference_shows(rest_api) -> None:
    """line is null and summaries hold the target type's summary field - the frontend's fallback"""
    reference = _reference(rest_api, PLAIN_REFERRER_ID, PLAIN_REF_FIELD)

    assert reference['object_id'] == TARGET_OBJECT_ID
    assert reference['line'] is None
    assert _summary_values(reference) == [TARGET_NAME]


def test_a_line_with_a_placeholder_is_filled_and_keeps_its_summaries(rest_api) -> None:
    """The line is what shows; the summaries still travel with it"""
    reference = _reference(rest_api, PLACEHOLDER_REFERRER_ID, PLACEHOLDER_REF_FIELD)

    assert reference['line'] == PLACEHOLDER_LINE.format(TARGET_NAME)
    assert _summary_values(reference) == [TARGET_NAME]


def test_a_line_without_placeholders_clears_the_summaries(rest_api) -> None:
    """A static line carries everything, so no summary fields are sent beside it"""
    reference = _reference(rest_api, STATIC_REFERRER_ID, STATIC_REF_FIELD)

    assert reference['line'] == STATIC_LINE
    assert reference['summaries'] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                  an entry missing one of its optional keys                                           #
# -------------------------------------------------------------------------------------------------------------------- #
MISSING_KEY_TYPE_ID: int = 93716
MISSING_KEY_REFERRER_ID: int = 93717
NO_PREFIX_FIELD: str = 'ref-no-prefix'
NO_FIELDS_FIELD: str = 'ref-no-fields'
NO_LINE_FIELD: str = 'ref-no-line'
ROUTE_TYPE_NAME: str = 'reference-summaries-route'
ROUTE_REFERRER_ID: int = 93718


def _entry_without(key: str, line: str) -> dict[str, Any]:
    """A complete nested-summary entry for the target type, minus one key - as the type import stores it."""
    entry: dict[str, Any] = {'type_id': TARGET_TYPE_ID, 'line': line, 'label': 'Target', 'fields': [NAME_FIELD],
                             'icon': 'fa-cube', 'prefix': False}
    del entry[key]

    return entry


@pytest.fixture(name='missing_key_referrer')
def fixture_missing_key_referrer(database_manager: MongoDatabaseManager, database_name: str):
    """A stored referring type whose three reference fields each lack one key; one object using all three."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.delete_many({'public_id': MISSING_KEY_TYPE_ID})
    objects.delete_many({'public_id': MISSING_KEY_REFERRER_ID})

    fields: list[dict[str, Any]] = [
        {'type': 'ref', 'name': name, 'label': name, 'ref_types': [TARGET_TYPE_ID], 'summaries': [entry]}
        for name, entry in ((NO_PREFIX_FIELD, _entry_without('prefix', PLACEHOLDER_LINE)),
                            (NO_FIELDS_FIELD, _entry_without('fields', STATIC_LINE)),
                            (NO_LINE_FIELD, _entry_without('line', PLACEHOLDER_LINE)))
    ]
    types.insert_one(_type_doc(MISSING_KEY_TYPE_ID, fields, []))
    objects.insert_one(_object_doc(MISSING_KEY_REFERRER_ID, MISSING_KEY_TYPE_ID, [
        {'name': name, 'value': TARGET_OBJECT_ID} for name in (NO_PREFIX_FIELD, NO_FIELDS_FIELD, NO_LINE_FIELD)
    ]))
    yield
    types.delete_many({'public_id': MISSING_KEY_TYPE_ID})
    objects.delete_many({'public_id': MISSING_KEY_REFERRER_ID})


def test_an_entry_without_prefix_renders_with_the_schema_default(rest_api, missing_key_referrer) -> None:
    """The line is filled, and `prefix` is what the type route would have stored"""
    reference = _reference(rest_api, MISSING_KEY_REFERRER_ID, NO_PREFIX_FIELD)

    assert reference['prefix'] is True
    assert reference['line'] == PLACEHOLDER_LINE.format(TARGET_NAME)


def test_an_entry_without_fields_renders_its_line(rest_api, missing_key_referrer) -> None:
    """No `fields` is an empty list: the static line is shown"""
    reference = _reference(rest_api, MISSING_KEY_REFERRER_ID, NO_FIELDS_FIELD)

    assert reference['line'] == STATIC_LINE


def test_an_entry_without_a_line_renders_its_summary_fields(rest_api, missing_key_referrer) -> None:
    """No `line` is no line: the summary fields are what the reference shows"""
    reference = _reference(rest_api, MISSING_KEY_REFERRER_ID, NO_LINE_FIELD)

    assert reference['line'] is None
    assert _summary_values(reference) == [TARGET_NAME]


@pytest.fixture(name='route_written_type')
def fixture_route_written_type(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A referring type saved through POST /types/ with a nested summary that sends no `fields`; yields its id."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.delete_many({'name': ROUTE_TYPE_NAME})
    objects.delete_many({'public_id': ROUTE_REFERRER_ID})

    payload: dict[str, Any] = {
        'name': ROUTE_TYPE_NAME, 'label': 'Reference Summaries Route', 'author_id': 1, 'active': True,
        'version': '1.0.0', 'selectable_as_parent': True, 'global_template_ids': [],
        'fields': [{'type': 'ref', 'name': STATIC_REF_FIELD, 'label': 'Ref', 'ref_types': [TARGET_TYPE_ID],
                    'summaries': [_entry_without('fields', STATIC_LINE)]}],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': []},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                                      'fields': [STATIC_REF_FIELD]}]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }
    response = rest_api.post('/types/', json=payload)
    assert response.status_code == HTTPStatus.CREATED
    type_id: int = response.get_json()['result_id']

    objects.insert_one(_object_doc(ROUTE_REFERRER_ID, type_id, [{'name': STATIC_REF_FIELD,
                                                                  'value': TARGET_OBJECT_ID}]))
    yield type_id
    types.delete_many({'name': ROUTE_TYPE_NAME})
    objects.delete_many({'public_id': ROUTE_REFERRER_ID})


def test_the_type_route_stores_the_fields_default(route_written_type: int, database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
    """A nested summary saved without `fields` is stored with an empty list"""
    stored = database_manager.get_collection(CmdbType.COLLECTION, database_name).find_one(
        {'public_id': route_written_type})

    assert stored['fields'][0]['summaries'][0]['fields'] == []


def test_a_type_saved_without_summary_fields_renders_its_references(rest_api, route_written_type: int) -> None:
    """The reference shows its line, rather than the icon and label alone"""
    reference = _reference(rest_api, ROUTE_REFERRER_ID, STATIC_REF_FIELD)

    assert reference['line'] == STATIC_LINE
