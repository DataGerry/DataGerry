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
Functional tests for the ``special_type`` marker of an object created through ``POST /objects/``

Seeds a type carrying a marker and a plain one. Pinned:

  - the stored marker is the type's: when the body leaves it out, and when the body sends another one
  - the render answers it in ``object_information``, which is what the frontend picks the object page's overview by
  - a PUT leaving the key out keeps the marker and is not refused as a marker change
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.rendering.render_constants import RenderObjectInfoKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'

MARKED_TYPE: int = 48601
PLAIN_TYPE: int = 48602
TYPE_IDS: list[int] = [MARKED_TYPE, PLAIN_TYPE]
CREATED: int = 48611
MARKER: str = 'PERSON'
LABEL_FIELD: str = 'display_name'


def _type(public_id: int, marker: str | None) -> dict[str, Any]:
    """A type with one text field"""
    return {
        'public_id': public_id, 'name': f'marker-{public_id}', 'label': 'Marker', 'author_id': 1, 'active': True,
        'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': marker,
        'fields': [{'type': 'text', 'name': LABEL_FIELD, 'label': 'Name'}],
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': []}, 'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [LABEL_FIELD]},
        ]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _body(type_id: int, **extra: Any) -> dict[str, Any]:
    """A create body"""
    return {'public_id': CREATED, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': LABEL_FIELD, 'value': 'Ada'}], **extra}


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The two types; the created object removed before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': CREATED})

    _purge()
    types.insert_many([_type(MARKED_TYPE, MARKER), _type(PLAIN_TYPE, None)])
    yield objects
    _purge()


@pytest.mark.parametrize('type_id, extra, stored', [
    (MARKED_TYPE, {}, MARKER),
    (MARKED_TYPE, {'special_type': 'SUBNET'}, MARKER),
    (MARKED_TYPE, {'special_type': None}, MARKER),
    (PLAIN_TYPE, {'special_type': 'SUBNET'}, None),
    (PLAIN_TYPE, {}, None),
], ids=['omitted', 'another-marker', 'null', 'marker-on-a-plain-type', 'plain'])
def test_the_stored_marker_is_the_types(rest_api, objects: Any, type_id: int, extra: dict[str, Any],
                                        stored: str | None) -> None:
    """Whatever the body says"""
    response = rest_api.post(f'{OBJECTS_URL}/', json=_body(type_id, **extra))

    assert response.status_code == HTTPStatus.OK, response.get_json()
    assert objects.find_one({'public_id': CREATED})['special_type'] == stored


def test_the_render_answers_the_marker(rest_api, objects: Any) -> None:
    """The frontend shows the special type's overview by it"""
    assert rest_api.post(f'{OBJECTS_URL}/', json=_body(MARKED_TYPE)).status_code == HTTPStatus.OK
    assert objects.count_documents({'public_id': CREATED}) == 1

    rendered = rest_api.get(f'{OBJECTS_URL}/{CREATED}').get_json()

    assert rendered['object_information'][RenderObjectInfoKey.SPECIAL_TYPE.value] == MARKER


def test_a_put_leaving_the_marker_out_keeps_it(rest_api, objects: Any) -> None:
    """Not a marker change"""
    assert rest_api.post(f'{OBJECTS_URL}/', json=_body(MARKED_TYPE)).status_code == HTTPStatus.OK

    response = rest_api.put(f'{OBJECTS_URL}/{CREATED}', json={'type_id': MARKED_TYPE, 'fields': [
        {'name': LABEL_FIELD, 'value': 'Bob'}]})

    assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
    assert objects.find_one({'public_id': CREATED})['special_type'] == MARKER
