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
Functional tests of a CmdbType whose sections, summary or external links name fields it does not declare

A Type stored that way saves when sent back unchanged - the stale names are dropped. An update removing a field
also drops the field from the external links naming it, which the type builder does not do itself. A name an
update newly writes is still refused. The type import drops every such name from an upload, on both verbs
"""
import copy
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types/'
IMPORT_CREATE_URL: str = '/import/type/create/'
IMPORT_UPDATE_URL: str = '/import/type/update/'
STALE_TYPE_ID: int = 99401
STALE_NAME: str = 'stale-references'
LINKED_NAME: str = 'stale-references-linked'
IMPORTED_NAME: str = 'stale-references-imported'
GHOST: str = 'radio-ghost'
KEPT: str = 'text-kept'
LINKED: str = 'text-linked'


def _field(name: str) -> dict[str, Any]:
    """A text field."""
    return {'type': 'text', 'name': name, 'label': name.title()}


def _link(fields: list[str]) -> dict[str, Any]:
    """An external link naming the given fields."""
    return {'name': 'wiki', 'label': 'Wiki', 'href': 'https://wiki/{}', 'icon': 'fa-link', 'fields': fields}


def _stale_type() -> dict[str, Any]:
    """A Type whose section, summary and external link still name a field it no longer declares."""
    return make_type_doc(STALE_TYPE_ID, STALE_NAME, fields=[_field(KEPT)]) | {'render_meta': {
        'icon': 'fa-cube', 'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [KEPT, GHOST]}],
        'summary': {'fields': [KEPT, GHOST]}, 'externals': [_link([GHOST, 'object_id'])],
    }}


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """The type collection, holding the stale Type; every Type of these tests removed afterwards"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{'public_id': STALE_TYPE_ID},
                                        {'name': {'$in': [STALE_NAME, LINKED_NAME, IMPORTED_NAME]}}]})

    _purge()
    collection.insert_one(_stale_type())
    yield collection
    _purge()


def _render_meta(types, **criteria: Any) -> dict[str, Any]:
    """The stored render_meta of one Type."""
    return types.find_one(criteria)['render_meta']


def _assert_ghost_gone(render_meta: dict[str, Any]) -> None:
    """Every place lost the stale name and kept the rest."""
    assert render_meta['sections'][0]['fields'] == [KEPT]
    assert render_meta['summary']['fields'] == [KEPT]
    assert render_meta['externals'][0]['fields'] == ['object_id']


def _import(rest_api, url: str, entry: dict[str, Any]) -> list[str]:
    """The errors of an import's partial report."""
    response = rest_api.post(url, data={'uploadFile': json.dumps([entry], default=str)},
                             content_type='multipart/form-data')

    return [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]


class TestUpdate:
    """PUT /types/<id>"""

    def test_a_stale_type_sent_back_as_read_is_saved_without_its_stale_names(self, rest_api, types) -> None:
        """The client changed nothing"""
        read = rest_api.get(f'{TYPES_URL}{STALE_TYPE_ID}').get_json()['result']

        response = rest_api.put(f'{TYPES_URL}{STALE_TYPE_ID}', json=read)

        assert response.status_code == HTTPStatus.ACCEPTED
        _assert_ghost_gone(_render_meta(types, public_id=STALE_TYPE_ID))

    def test_a_name_the_update_newly_writes_is_refused(self, rest_api, types) -> None:
        """Into a list that did not carry it; the stored Type stays"""
        read = rest_api.get(f'{TYPES_URL}{STALE_TYPE_ID}').get_json()['result']
        read['render_meta']['externals'].append(_link(['text-unknown']) | {'name': 'other'})

        response = rest_api.put(f'{TYPES_URL}{STALE_TYPE_ID}', json=read)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'text-unknown' in response.get_json()['message']
        assert _render_meta(types, public_id=STALE_TYPE_ID)['sections'][0]['fields'] == [KEPT, GHOST]

    def test_removing_a_field_drops_it_from_the_external_link(self, rest_api, types) -> None:
        """What the builder sends: the field and its section entry gone, the link untouched"""
        payload = make_type_doc(0, LINKED_NAME, fields=[_field(KEPT), _field(LINKED)]) | {'render_meta': {
            'icon': 'fa-cube', 'summary': {'fields': [KEPT]}, 'externals': [_link([LINKED])],
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [KEPT, LINKED]}]}}
        for server_owned in ('public_id', 'creation_time'):
            payload.pop(server_owned, None)
        created = rest_api.post(TYPES_URL, json=payload)
        assert created.status_code in (HTTPStatus.OK, HTTPStatus.CREATED), created.get_json()
        stored: dict[str, Any] = created.get_json()['raw']
        edited = copy.deepcopy(stored)
        edited['fields'] = [_field(KEPT)]
        edited['render_meta']['sections'][0]['fields'] = [KEPT]

        response = rest_api.put(f"{TYPES_URL}{stored['public_id']}", json=edited)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _render_meta(types, name=LINKED_NAME)['externals'][0]['fields'] == []


@pytest.mark.usefixtures('types')
class TestImport:
    """An export of a stale Type"""

    def test_a_create_drops_the_stale_names(self, rest_api, types) -> None:
        """Imported as a new Type"""
        entry = _stale_type() | {'name': IMPORTED_NAME}
        entry.pop('public_id')

        assert not _import(rest_api, IMPORT_CREATE_URL, entry)
        _assert_ghost_gone(_render_meta(types, name=IMPORTED_NAME))

    def test_an_update_drops_the_stale_names(self, rest_api, types) -> None:
        """Written over the stored stale Type"""
        assert not _import(rest_api, IMPORT_UPDATE_URL, _stale_type())
        _assert_ghost_gone(_render_meta(types, public_id=STALE_TYPE_ID))
