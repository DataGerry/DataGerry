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
Functional tests for the audit keys of a CmdbType: who created it and when, who edited it last and when

All four are the server's. Measured before: a create stored a body's creation_time, last_edit_time and editor_id,
an update stored a body's author_id and creation_time - rewriting who made the Type and when - and a body without
author_id was refused, though the server stamps it. Now the request schema drops the four keys, the create stamps
the caller and now with an empty edit half, and the update keeps the stored author and creation time. The frontend
still sends them (author_id on create, the loaded Type's keys on update); those requests keep working
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest
from pymongo.collection import Collection

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types'
TYPE_NAME: str = 'type-audit-keys'
CALLER_ID: int = 1                      # the rest_api client's full-access user
FORGED_AUTHOR_ID: int = 77
FORGED_EDITOR_ID: int = 5
# The frontend's wire form of a date: {'$date': epoch milliseconds}
FORGED_CREATION: dict[str, int] = {'$date': 978307200000}      # 2001-01-01
FORGED_EDIT: dict[str, int] = {'$date': 978393600000}          # 2001-01-02
FORGED_YEAR: int = 2001


def _payload(**overrides: Any) -> dict[str, Any]:
    """A minimal valid Type body; the audit keys only when a test adds them."""
    payload: dict[str, Any] = {
        'name': TYPE_NAME, 'label': 'Audit Keys', 'active': True, 'version': '1.0.0', 'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [{'type': 'text', 'name': 'hostname', 'label': 'Hostname'}],
        'render_meta': {
            'icon': 'fa-cube', 'externals': [],
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['hostname']}],
            'summary': {'fields': ['hostname']},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }
    payload.update(overrides)

    return payload


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Collection]:
    """The type collection, the module's Type removed around each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'name': TYPE_NAME})
    yield types
    types.delete_many({'name': TYPE_NAME})


def _stored(types: Collection) -> dict[str, Any]:
    """The module's Type as stored."""
    return types.find_one({'name': TYPE_NAME})


def _created(rest_api, types: Collection, **overrides: Any) -> dict[str, Any]:
    """Creates the Type through the route and answers it as stored."""
    response = rest_api.post(f'{TYPES_URL}/', json=_payload(**overrides))

    assert response.status_code == HTTPStatus.CREATED, response.get_json()

    return _stored(types)


class TestTheCreate:
    """POST /types/ - the caller and now, never edited"""

    def test_a_body_cannot_set_any_audit_key(self, rest_api, types: Collection) -> None:
        """Before: the body's creation time, edit time and editor were stored (author_id was already overwritten)"""
        before: datetime = datetime.now(timezone.utc).replace(tzinfo=None)

        stored = _created(rest_api, types, author_id=FORGED_AUTHOR_ID, creation_time=FORGED_CREATION,
                          last_edit_time=FORGED_EDIT, editor_id=FORGED_EDITOR_ID)

        assert stored['author_id'] == CALLER_ID
        assert stored['creation_time'] >= before
        assert stored['last_edit_time'] is None
        assert stored['editor_id'] is None

    def test_a_body_without_author_id_is_accepted(self, rest_api, types: Collection) -> None:
        """Before: 400 'author_id: required field' for a key the server stamps anyway"""
        assert _created(rest_api, types)['author_id'] == CALLER_ID

    def test_the_frontends_create_shape(self, rest_api, types: Collection) -> None:
        """The type builder sends the current user as author_id - accepted, stamped the same"""
        assert _created(rest_api, types, author_id=CALLER_ID)['author_id'] == CALLER_ID


class TestTheUpdate:
    """PUT /types/<id> - the stored history kept, the caller the editor"""

    def test_a_body_cannot_rewrite_the_history(self, rest_api, types: Collection) -> None:
        """Before: the body's author_id and creation_time replaced the stored ones"""
        created = _created(rest_api, types)

        response = rest_api.put(f"{TYPES_URL}/{created['public_id']}", json=_payload(
            label='Edited', author_id=FORGED_AUTHOR_ID, creation_time=FORGED_CREATION,
            last_edit_time=FORGED_EDIT, editor_id=FORGED_EDITOR_ID,
        ))

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        stored = _stored(types)
        assert stored['label'] == 'Edited'
        assert stored['author_id'] == created['author_id']
        assert stored['creation_time'] == created['creation_time']
        assert stored['editor_id'] == CALLER_ID
        assert stored['last_edit_time'].year != FORGED_YEAR

    def test_a_body_without_author_id_is_accepted(self, rest_api, types: Collection) -> None:
        """Before: 400 'author_id: required field'"""
        created = _created(rest_api, types)

        response = rest_api.put(f"{TYPES_URL}/{created['public_id']}", json=_payload(label='Edited'))

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        assert _stored(types)['author_id'] == created['author_id']

    def test_the_frontends_update_shape(self, rest_api, types: Collection) -> None:
        """The builder sends the loaded Type back - its own audit keys plus itself as editor; accepted, history kept"""
        created = _created(rest_api, types)
        loaded: dict[str, Any] = rest_api.get(f"{TYPES_URL}/{created['public_id']}").get_json()['result']
        body: dict[str, Any] = {key: loaded[key] for key in _payload() if key in loaded}
        body.update(label='Edited', author_id=loaded['author_id'], creation_time=loaded['creation_time'],
                    editor_id=CALLER_ID)

        response = rest_api.put(f"{TYPES_URL}/{created['public_id']}", json=body)

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        assert _stored(types)['creation_time'] == created['creation_time']
