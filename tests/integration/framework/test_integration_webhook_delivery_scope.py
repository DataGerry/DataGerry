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
Integration tests for the owner scope of webhook deliveries, against a real MongoDB and real loopback receivers

An object of a type whose ACL leaves one group out is deleted through the REST app. Two webhooks listen, each with
its own HTTP server on the loopback interface (let through the destination check the way an operator allowlist
would): one owned by the admin, one by a user of the left-out group. Asserted:

  - the admin's receiver gets the POST, carrying the deleted object; the other receiver sees no request at all
  - only the delivered webhook has a CmdbWebhookEvent
  - once the narrow owner's webhook is saved again by the admin, it becomes the admin's and receives the next one
"""
import json
import threading
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.interface.rest_api.routes.webhook_routes.webhook_destination import refused_destination_reason
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook

from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

LOOPBACK: str = '127.0.0.1'
LOOPBACK_NETWORK: str = '127.0.0.0/8'
ADMIN_USER_ID: int = 1
ADMIN_GROUP: str = '1'
NARROW_GROUP_ID: int = 2

DENIED_TYPE_ID: int = 98501
OBJECT_ID: int = 98511
SECOND_OBJECT_ID: int = 98512
NARROW_OWNER_ID: int = 98521
ADMIN_HOOK_ID: int = 98531
NARROW_HOOK_ID: int = 98532
ALL_HOOK_IDS: list[int] = [ADMIN_HOOK_ID, NARROW_HOOK_ID]


def _receiver() -> tuple[HTTPServer, list[dict[str, Any]]]:
    """A loopback HTTP server recording the JSON bodies POSTed to it"""
    received: list[dict[str, Any]] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # pylint: disable=invalid-name
            """Records the body and answers 200"""
            received.append(json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)))))
            self.send_response(HTTPStatus.OK)
            self.end_headers()

        def log_message(self, *_args: Any) -> None:
            """Silent"""

    server = HTTPServer((LOOPBACK, 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    return server, received


def _url(server: HTTPServer) -> str:
    """The server's URL"""
    return f'http://{LOOPBACK}:{server.server_address[1]}/hook'


@pytest.fixture(name='receivers')
def fixture_receivers(database_manager: MongoDatabaseManager, database_name: str,
                      monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[int, list[dict[str, Any]]]]:
    """Seeds the type, objects, owner and two webhooks on two receivers; purges and stops them after"""
    def _collection(name: str):
        return database_manager.get_collection(name, database_name)

    def _purge() -> None:
        _collection(CmdbType.COLLECTION).delete_many({'public_id': DENIED_TYPE_ID})
        _collection(CmdbObject.COLLECTION).delete_many({'public_id': {'$in': [OBJECT_ID, SECOND_OBJECT_ID]}})
        _collection(CmdbUser.COLLECTION).delete_many({'public_id': NARROW_OWNER_ID})
        _collection(CmdbWebhook.COLLECTION).delete_many({'public_id': {'$in': ALL_HOOK_IDS}})
        _collection(CmdbWebhookEvent.COLLECTION).delete_many({'webhook_id': {'$in': ALL_HOOK_IDS}})

    admin_server, admin_received = _receiver()
    narrow_server, narrow_received = _receiver()
    _purge()
    denied_type = make_type_doc(DENIED_TYPE_ID, 'webhook-scope-integration')
    denied_type['acl'] = {'activated': True,
                          'groups': {'includes': {ADMIN_GROUP: ['CREATE', 'READ', 'UPDATE', 'DELETE']}}}
    _collection(CmdbType.COLLECTION).insert_one(denied_type)
    _collection(CmdbObject.COLLECTION).insert_many([
        make_object_doc(OBJECT_ID, DENIED_TYPE_ID, [make_field('dg-name', 'first')]),
        make_object_doc(SECOND_OBJECT_ID, DENIED_TYPE_ID, [make_field('dg-name', 'second')]),
    ])
    _collection(CmdbUser.COLLECTION).insert_one(
        {'public_id': NARROW_OWNER_ID, 'user_name': 'scope-integration', 'active': True, 'group_id': NARROW_GROUP_ID})
    _collection(CmdbWebhook.COLLECTION).insert_many([
        {'public_id': ADMIN_HOOK_ID, 'name': 'Admin hook', 'url': _url(admin_server), 'event_types': ['DELETE'],
         'active': True, 'owner_id': ADMIN_USER_ID},
        {'public_id': NARROW_HOOK_ID, 'name': 'Narrow hook', 'url': _url(narrow_server), 'event_types': ['DELETE'],
         'active': True, 'owner_id': NARROW_OWNER_ID},
    ])
    monkeypatch.setattr(webhook_helper.DISPATCH_EXECUTOR, 'submit', lambda fn, *args, **kwargs: fn(*args, **kwargs))
    monkeypatch.setattr(webhook_helper, 'refused_destination_reason',
                        lambda url: refused_destination_reason(url, [LOOPBACK_NETWORK]))

    yield {ADMIN_HOOK_ID: admin_received, NARROW_HOOK_ID: narrow_received}

    _purge()
    for server in (admin_server, narrow_server):
        server.shutdown()
        server.server_close()


def _recorded(database_manager: MongoDatabaseManager, database_name: str) -> list[int]:
    """The webhooks a CmdbWebhookEvent was recorded for"""
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)

    return sorted(event['webhook_id'] for event in events.find({'webhook_id': {'$in': ALL_HOOK_IDS}}))


def test_only_the_owner_who_may_read_receives_the_object(rest_api, receivers, database_manager,
                                                         database_name) -> None:
    """The narrow owner's receiver sees no request; only the delivery is recorded"""
    assert rest_api.delete(f'/objects/{OBJECT_ID}').status_code == HTTPStatus.OK

    assert [body['object_before']['public_id'] for body in receivers[ADMIN_HOOK_ID]] == [OBJECT_ID]
    assert receivers[NARROW_HOOK_ID] == []
    assert _recorded(database_manager, database_name) == [ADMIN_HOOK_ID]


def test_saving_the_webhook_again_moves_it_to_the_editor(rest_api, receivers, database_manager,
                                                         database_name) -> None:
    """The admin saves the narrow webhook unchanged: it is the admin's now, and the next delete reaches it"""
    webhooks = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)
    stored = webhooks.find_one({'public_id': NARROW_HOOK_ID}, {'_id': 0, 'owner_id': 0, 'public_id': 0})
    assert rest_api.put(f'/webhooks/{NARROW_HOOK_ID}', json=stored).status_code in (HTTPStatus.OK,
                                                                                   HTTPStatus.ACCEPTED)

    assert rest_api.delete(f'/objects/{SECOND_OBJECT_ID}').status_code == HTTPStatus.OK

    assert [body['object_before']['public_id'] for body in receivers[NARROW_HOOK_ID]] == [SECOND_OBJECT_ID]
    assert _recorded(database_manager, database_name) == [ADMIN_HOOK_ID, NARROW_HOOK_ID]
