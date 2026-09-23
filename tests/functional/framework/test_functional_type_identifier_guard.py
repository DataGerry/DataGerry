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
A CmdbType field's and multi-data-section's identifier cannot be renamed

These are the three reproductions that found the bug, turned into regression tests. Before
Unguarded, each of them answers **202** and destroys data without a word:

  1. renaming a flat field      -> the Object's value became ``None``
  2. renaming an MDS field      -> the row's value became ``None``
  3. renaming an MDS section    -> the Object's ``multi_data_sections`` was emptied ENTIRELY

The cause is the same in all three: a field and a section are identified by their **name** and by
nothing else, so the realignment that follows a Type update reads a rename as one removal plus one
addition. `CLAUDE.md` had always stated that a field name is the unique, immutable identifier - the
backend simply never enforced it, and the frontend not offering a rename was the whole protection.

**The payload is round-tripped, never hand-built.** The stored Type is read back through
`GET /types/<id>` and only the identifier is changed, so the request is schema-valid by construction -
the first attempt at this reproduction was rejected by the Cerberus validator for an unrelated reason
and looked like the guard working.
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

TYPE_ID: int = 9840
OBJECT_ID: int = 9850

FLAT_FIELD: str = 'dg-hostname'
MDS_SECTION: str = 'dg-interfaces'
MDS_FIELD: str = 'dg-row-value'

FLAT_VALUE: str = 'srv-prod-01'
ROW_VALUE: str = 'row-value-A'


def _type_doc(mds_section: str = MDS_SECTION, mds_field: str = MDS_FIELD,
              flat_field: str = FLAT_FIELD) -> dict[str, Any]:
    """A CmdbType with one ordinary field and one multi-data-section holding one field."""
    return {
        'public_id': TYPE_ID,
        'name': 'identifier_guard_type',
        'label': 'Identifier Guard',
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'version': '1.0.0',
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [
            {'type': 'text', 'name': flat_field, 'label': 'Hostname'},
            {'type': 'text', 'name': mds_field, 'label': 'Row value'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'externals': [],
            'sections': [
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [flat_field]},
                {'type': 'multi-data-section', 'name': mds_section, 'label': 'Interfaces',
                 'fields': [mds_field]},
            ],
            'summary': {'fields': [flat_field]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc() -> dict[str, Any]:
    """One Object of the Type, holding a flat value and one MDS row."""
    return {
        'public_id': OBJECT_ID,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'name': FLAT_FIELD, 'value': FLAT_VALUE}],
        'multi_data_sections': [{
            'section_id': MDS_SECTION,
            'highest_id': 1,
            'values': [{'multi_data_id': 1,
                        'data': [{'name': MDS_FIELD, 'value': ROW_VALUE, 'type': 'text'}]}],
        }],
    }


@pytest.fixture(name='stored')
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Type and one Object of it, and yields both collections."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': OBJECT_ID})

    _purge()
    types.insert_one(_type_doc())
    objects.insert_one(_object_doc())

    yield types, objects

    _purge()


def _read_back(rest_api) -> dict[str, Any]:
    """The stored Type as the route hands it out - the only schema-valid starting point for a PUT."""
    return rest_api.get(f'{ROUTE_URL}/{TYPE_ID}').get_json()['result']


def _flat_value(objects) -> Any:
    """The Object's stored value for the flat field, whatever the field is currently called."""
    return next(iter(objects.find_one({'public_id': OBJECT_ID})['fields']), {}).get('value')


def _mds_sections(objects) -> list[dict[str, Any]]:
    """The Object's multi_data_sections as stored."""
    return objects.find_one({'public_id': OBJECT_ID}).get('multi_data_sections', [])


class TestRenamingAFlatFieldIsRefused:
    """Reproduction 1 — an accepted rename answers 202 and leaves a null value."""

    def test_the_rename_is_refused(self, rest_api, stored) -> None:
        """A field's name is its identifier; changing it would empty every Object's value."""
        del stored
        payload = _read_back(rest_api)
        payload['fields'][0]['name'] = 'dg-host-name'
        payload['render_meta']['sections'][0]['fields'] = ['dg-host-name']
        payload['render_meta']['summary']['fields'] = ['dg-host-name']

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_refusal_names_both_identifiers(self, rest_api, stored) -> None:
        """So the caller can see what the swap was, not just that one happened."""
        del stored
        payload = _read_back(rest_api)
        payload['fields'][0]['name'] = 'dg-host-name'
        payload['render_meta']['sections'][0]['fields'] = ['dg-host-name']
        payload['render_meta']['summary']['fields'] = ['dg-host-name']

        message = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload).get_json()['message']

        assert FLAT_FIELD in message
        assert 'dg-host-name' in message

    def test_the_stored_value_survives(self, rest_api, stored) -> None:
        """The point of the whole guard: nothing is written, so nothing is lost."""
        _types, objects = stored
        payload = _read_back(rest_api)
        payload['fields'][0]['name'] = 'dg-host-name'
        payload['render_meta']['sections'][0]['fields'] = ['dg-host-name']
        payload['render_meta']['summary']['fields'] = ['dg-host-name']

        rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert _flat_value(objects) == FLAT_VALUE


class TestRenamingAnMdsIdentifierIsRefused:
    """Reproductions 2 and 3 — the section case wiped every row."""

    def test_renaming_an_mds_field_is_refused(self, rest_api, stored) -> None:
        """An MDS field is declared in the flat `fields` list, so the field guard covers it."""
        _types, objects = stored
        payload = _read_back(rest_api)
        payload['fields'][1]['name'] = 'dg-row-value-renamed'
        payload['render_meta']['sections'][1]['fields'] = ['dg-row-value-renamed']

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _mds_sections(objects)[0]['values'][0]['data'][0]['value'] == ROW_VALUE

    def test_renaming_an_mds_section_is_refused(self, rest_api, stored) -> None:
        """
        The worst of the three: the propagation matches sections on (type, name)

        A renamed section reads as one the Type no longer declares, and every Object drops **all** of
        its rows for it.
        """
        _types, objects = stored
        payload = _read_back(rest_api)
        payload['render_meta']['sections'][1]['name'] = 'dg-interfaces-renamed'

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _mds_sections(objects), 'the rows must still be there'
        assert _mds_sections(objects)[0]['section_id'] == MDS_SECTION

    def test_the_section_refusal_names_both_identifiers(self, rest_api, stored) -> None:
        """The message has to say which section, since a Type may declare several."""
        del stored
        payload = _read_back(rest_api)
        payload['render_meta']['sections'][1]['name'] = 'dg-interfaces-renamed'

        message = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload).get_json()['message']

        assert MDS_SECTION in message
        assert 'dg-interfaces-renamed' in message


class TestWhatStaysAllowed:
    """The guard is about renaming. Everything else a Type edit does is untouched."""

    def test_a_metadata_only_edit_still_works(self, rest_api, stored) -> None:
        """Label, icon, regex, ordering - nothing that touches an identifier."""
        del stored
        payload = _read_back(rest_api)
        payload['label'] = 'Renamed Label'
        payload['fields'][0]['label'] = 'Host name'

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_adding_a_field_still_works(self, rest_api, stored) -> None:
        """A pure addition cannot lose anything."""
        del stored
        payload = _read_back(rest_api)
        payload['fields'].append({'type': 'text', 'name': 'dg-extra', 'label': 'Extra'})
        payload['render_meta']['sections'][0]['fields'].append('dg-extra')

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_removing_a_field_outright_still_works(self, rest_api, stored) -> None:
        """
        Dropping a field remains supported, and still drops the stored value

        That is existing, documented behaviour and deliberately NOT changed here - this guard refuses
        renaming, not removal.
        """
        del stored
        payload = _read_back(rest_api)
        payload['fields'] = [field for field in payload['fields'] if field['name'] != MDS_FIELD]
        payload['render_meta']['sections'] = [
            section for section in payload['render_meta']['sections']
            if section['name'] != MDS_SECTION
        ]

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_a_rename_is_allowed_while_the_type_has_no_objects(
        self, rest_api, stored, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        A Type still being designed carries no values to lose

        Every sibling guard on this route is conditioned the same way, and type building happens
        before any Object exists - refusing there would block ordinary modelling work.
        """
        del stored
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
            {'public_id': OBJECT_ID},
        )
        payload = _read_back(rest_api)
        payload['fields'][0]['name'] = 'dg-host-name'
        payload['render_meta']['sections'][0]['fields'] = ['dg-host-name']
        payload['render_meta']['summary']['fields'] = ['dg-host-name']

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED
