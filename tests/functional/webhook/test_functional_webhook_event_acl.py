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
Functional tests for the object ACL of the webhook delivery log, through the real REST app

The test user's group is denied READ on one type. For an event sent for an object of that type:

  - the list and the single read answer ``object_before``, ``object_after`` and ``changes`` as ``null``, and the
    rest of the row as stored
  - a ``?filter=`` stage matching one of its field values finds nothing - the values are gone before the caller's
    stages run

An event for an object the user may read keeps its values on both routes.
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/webhook_events'

DENIED_TYPE_ID: int = 98101
ALLOWED_TYPE_ID: int = 98102
DENIED_EVENT_ID: int = 98111
DENIED_DELETE_EVENT_ID: int = 98112
ALLOWED_EVENT_ID: int = 98113
ALL_EVENT_IDS: list[int] = [DENIED_EVENT_ID, DENIED_DELETE_EVENT_ID, ALLOWED_EVENT_ID]
WEBHOOK_ID: int = 98121
SECRET_VALUE: str = 'acl-protected-secret'
PLAIN_VALUE: str = 'readable-value'
# A group the denied type grants READ - not the test user's
OTHER_GROUP_ID: str = '2'

VALUE_KEYS: tuple[str, ...] = ('object_before', 'object_after', 'changes')
ROW_KEYS: tuple[str, ...] = ('public_id', 'webhook_id', 'operation', 'status', 'response_code')


def _snapshot(type_id: int, value: str) -> dict[str, Any]:
    """An object snapshot as an event stores it"""
    return {'public_id': 5, 'type_id': type_id, 'fields': [{'name': 'secret', 'value': value}]}


def _event(public_id: int, type_id: int, value: str, operation: str = 'UPDATE') -> dict[str, Any]:
    """A stored event for an object of the given type; a DELETE carries only the before snapshot"""
    return {
        'public_id': public_id, 'event_time': None, 'operation': operation, 'webhook_id': WEBHOOK_ID,
        'object_before': _snapshot(type_id, value),
        'object_after': None if operation == 'DELETE' else _snapshot(type_id, value),
        'changes': {'old': [{'name': 'secret', 'value': value}], 'new': [{'name': 'secret', 'value': value}]},
        'response_code': 200, 'status': True,
    }


@pytest.fixture(name='events', autouse=True)
def fixture_events(database_manager: MongoDatabaseManager, database_name: str):
    """A denied type with an UPDATE and a DELETE event, an allowed type with one; purged after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [DENIED_TYPE_ID, ALLOWED_TYPE_ID]}})
        events.delete_many({'public_id': {'$in': ALL_EVENT_IDS}})

    _purge()
    denied_type = make_type_doc(DENIED_TYPE_ID, 'webhook-acl-denied')
    denied_type['acl'] = {'activated': True, 'groups': {'includes': {OTHER_GROUP_ID: ['READ']}}}
    types.insert_many([denied_type, make_type_doc(ALLOWED_TYPE_ID, 'webhook-acl-allowed')])
    events.insert_many([
        _event(DENIED_EVENT_ID, DENIED_TYPE_ID, SECRET_VALUE),
        _event(DENIED_DELETE_EVENT_ID, DENIED_TYPE_ID, SECRET_VALUE, operation='DELETE'),
        _event(ALLOWED_EVENT_ID, ALLOWED_TYPE_ID, PLAIN_VALUE),
    ])
    yield events
    _purge()


def _listed(rest_api, stages: list[dict[str, Any]] | None = None) -> dict[int, dict[str, Any]]:
    """The seeded events the list route answers, by public_id"""
    own: list[dict[str, Any]] = [{'$match': {'public_id': {'$in': ALL_EVENT_IDS}}}]
    response = rest_api.get(f'{ROUTE_URL}/?limit=0&filter={json.dumps(own + (stages or []))}')

    assert response.status_code == HTTPStatus.OK

    return {row['public_id']: row for row in response.get_json()['results']}


class TestTheList:
    """GET /webhook_events/"""

    def test_a_denied_event_keeps_its_row(self, rest_api, events) -> None:
        """Both the UPDATE and the DELETE (whose type comes from the before snapshot) are listed, unchanged"""
        rows = _listed(rest_api)

        for event_id in (DENIED_EVENT_ID, DENIED_DELETE_EVENT_ID):
            stored = events.find_one({'public_id': event_id})
            assert {key: rows[event_id][key] for key in ROW_KEYS} == {key: stored[key] for key in ROW_KEYS}

    def test_no_listed_row_carries_object_values(self, rest_api, events) -> None:
        """The list is the summary for every row, readable or not - the values are the single read's"""
        rows = _listed(rest_api)

        for event_id in (DENIED_EVENT_ID, DENIED_DELETE_EVENT_ID, ALLOWED_EVENT_ID):
            assert not set(VALUE_KEYS) & set(rows[event_id])

    def test_a_filter_on_a_masked_value_finds_nothing(self, rest_api, events) -> None:
        """The caller's stages run after the masking, so they cannot probe the values"""
        probe: list[dict[str, Any]] = [{'$match': {'object_before.fields.value': SECRET_VALUE}}]

        assert not _listed(rest_api, probe)

    def test_a_filter_on_a_readable_value_still_works(self, rest_api, events) -> None:
        """The masking takes nothing from an allowed event"""
        probe: list[dict[str, Any]] = [{'$match': {'object_after.fields.value': PLAIN_VALUE}}]

        assert set(_listed(rest_api, probe)) == {ALLOWED_EVENT_ID}


class TestTheSingleRead:
    """GET /webhook_events/<id>"""

    def test_a_denied_event_loses_its_values(self, rest_api, events) -> None:
        """The same rule as the list"""
        response = rest_api.get(f'{ROUTE_URL}/{DENIED_EVENT_ID}')

        assert response.status_code == HTTPStatus.OK
        event = response.get_json()
        assert all(event[key] is None for key in VALUE_KEYS)
        assert event['webhook_id'] == WEBHOOK_ID

    def test_an_allowed_event_keeps_its_values(self, rest_api, events) -> None:
        """Unchanged"""
        event = rest_api.get(f'{ROUTE_URL}/{ALLOWED_EVENT_ID}').get_json()

        assert event['object_after']['fields'][0]['value'] == PLAIN_VALUE
