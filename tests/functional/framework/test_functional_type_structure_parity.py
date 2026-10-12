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
Functional coverage that the type routes and the type import judge a type's structure alike

The same document - valid, or breaking one structure rule - is sent to ``POST /types/`` and to
``POST /import/type/create/``: both refuse it or both accept it - except a name in a section, the summary or an
external link that resolves to no declared field, which the route refuses and the import drops (an upload is an
export, the name was stale where it came from). A type the routes accept with an external link on ``object_id``
round-trips through the import, and an update is held to the same rules as a create
"""
import copy
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types/'
IMPORT_URL: str = '/import/type/create/'
ROUTE_NAME: str = 'parity-route'
IMPORT_NAME: str = 'parity-import'
UPDATE_TYPE_ID: int = 99301


def _base() -> dict[str, Any]:
    """A sound type: two text fields and a select in one section, a summary, no externals."""
    return {
        'label': 'Parity', 'author_id': 1, 'active': True, 'version': '1.0.0',
        'fields': [{'type': 'text', 'name': 'a', 'label': 'A'}, {'type': 'text', 'name': 'b', 'label': 'B'},
                   {'type': 'select', 'name': 's', 'label': 'S', 'options': [{'name': 'x', 'label': 'X'}]}],
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': ['a']}, 'externals': [],
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a', 'b', 's']}]},
        'acl': {'activated': False, 'groups': {'includes': {}}},
    }


def _variant(change: str) -> dict[str, Any]:
    """The sound type with one change applied."""
    doc = _base()
    meta = doc['render_meta']
    section = meta['sections'][0]

    if change == 'unknown-field-kind':
        doc['fields'][1]['type'] = 'nonsense'
    elif change == 'two-location-fields':
        doc['fields'] += [{'type': 'location', 'name': 'dg_location', 'label': 'L'},
                          {'type': 'location', 'name': 'loc2', 'label': 'L2'}]
        section['fields'] += ['dg_location', 'loc2']
    elif change == 'misnamed-location-field':
        doc['fields'].append({'type': 'location', 'name': 'where', 'label': 'W'})
        section['fields'].append('where')
    elif change == 'blank-field-label':
        doc['fields'][1]['label'] = ''
    elif change == 'blank-section-label':
        section['label'] = ''
    elif change == 'field-in-two-sections':
        meta['sections'].append({'type': 'section', 'name': 'two', 'label': 'Two', 'fields': ['a']})
    elif change == 'undefined-section-field':
        section['fields'].append('ghost')
    elif change == 'undefined-summary-field':
        meta['summary']['fields'].append('ghost')
    elif change == 'unknown-external-field':
        meta['externals'] = [{'name': 'l', 'label': 'L', 'href': 'https://x/{}', 'icon': 'x', 'fields': ['ghost']}]
    elif change == 'repeated-summary-field':
        meta['summary']['fields'] = ['a', 'a']
    elif change == 'orphan-field':
        section['fields'].remove('b')
    elif change == 'empty-section':
        meta['sections'].append({'type': 'section', 'name': 'empty', 'label': 'Empty', 'fields': []})
    elif change == 'select-without-options':
        doc['fields'][2]['options'] = []
    elif change == 'object-id-external':
        meta['externals'] = [{'name': 'l', 'label': 'L', 'href': 'https://x/{}', 'icon': 'x', 'fields': ['object_id']}]

    return doc


REFUSED: list[str] = ['unknown-field-kind', 'two-location-fields', 'misnamed-location-field', 'blank-field-label',
                      'blank-section-label', 'field-in-two-sections', 'repeated-summary-field']
STALE_NAME: list[str] = ['undefined-section-field', 'undefined-summary-field', 'unknown-external-field']
ROUTE_OWN_WORDING: set[str] = {'repeated-summary-field'}
ALLOWED: list[str] = ['orphan-field', 'empty-section', 'select-without-options', 'object-id-external']


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """The type collection, cleaned of every type these tests create"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{'name': {'$in': [ROUTE_NAME, IMPORT_NAME]}}, {'public_id': UPDATE_TYPE_ID}]})

    _purge()
    yield collection
    _purge()


def _via_route(rest_api, doc: dict[str, Any]):
    """POST /types/"""
    return rest_api.post(TYPES_URL, json={**copy.deepcopy(doc), 'name': ROUTE_NAME})


def _via_import(rest_api, doc: dict[str, Any]) -> list[str]:
    """POST /import/type/create/ - the errors of the partial report"""
    upload = json.dumps([{**copy.deepcopy(doc), 'name': IMPORT_NAME}])
    response = rest_api.post(IMPORT_URL, data={'uploadFile': upload}, content_type='multipart/form-data')

    return [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]


@pytest.mark.usefixtures('types')
class TestBothPathsAgree:
    """POST /types/ and the type import"""

    @pytest.mark.parametrize('change', REFUSED)
    def test_a_broken_structure_is_refused_by_both(self, rest_api, change: str) -> None:
        """With the same message - unless the route's own summary guard answers first"""
        response = _via_route(rest_api, _variant(change))
        import_errors = _via_import(rest_api, _variant(change))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert import_errors
        if change not in ROUTE_OWN_WORDING:
            assert response.get_json()['message'] in import_errors[0]

    @pytest.mark.parametrize('change', ALLOWED)
    def test_an_allowed_structure_is_accepted_by_both(self, rest_api, change: str) -> None:
        """Harmless on both"""
        assert _via_route(rest_api, _variant(change)).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert not _via_import(rest_api, _variant(change))


@pytest.mark.usefixtures('types')
class TestAStaleName:
    """A name resolving to no declared field"""

    @pytest.mark.parametrize('change', STALE_NAME)
    def test_the_route_refuses_it_and_the_import_drops_it(self, rest_api, types, change: str) -> None:
        """The import stores the type without the name"""
        assert _via_route(rest_api, _variant(change)).status_code == HTTPStatus.BAD_REQUEST
        assert not _via_import(rest_api, _variant(change))
        assert 'ghost' not in json.dumps(types.find_one({'name': IMPORT_NAME}, {'_id': 0})['render_meta'])


class TestRoundTripAndUpdate:
    """What a route created imports again; an update is judged like a create"""

    def test_a_type_with_an_object_id_link_re_imports(self, rest_api, types) -> None:
        """The stored document, uploaded as an export would carry it"""
        _via_route(rest_api, _variant('object-id-external'))
        stored: dict[str, Any] = types.find_one({'name': ROUTE_NAME}, {'_id': 0})
        stored.pop('public_id')

        assert not _via_import(rest_api, json.loads(json.dumps(stored, default=str)))

    def test_an_update_into_a_broken_structure_is_refused(self, rest_api, types) -> None:
        """The stored type stays"""
        types.insert_one({**_base(), 'name': ROUTE_NAME, 'public_id': UPDATE_TYPE_ID})
        broken = {**_variant('two-location-fields'), 'name': ROUTE_NAME, 'public_id': UPDATE_TYPE_ID}

        response = rest_api.put(f'{TYPES_URL}{UPDATE_TYPE_ID}', json=broken)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert len(types.find_one({'public_id': UPDATE_TYPE_ID})['fields']) == len(_base()['fields'])
