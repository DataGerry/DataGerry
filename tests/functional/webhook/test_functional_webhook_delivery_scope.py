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
Functional tests for the owner scope of webhook deliveries, through the real REST app

Objects are deleted through ``DELETE /objects/<id>`` by the test user (admin). Five webhooks listen, one per owner
kind: the admin, a user whose group the denied type leaves out, a deactivated admin, a deleted user, and none. For an
object of the denied type only the admin's webhook is posted to; for an object of a type without an ACL the narrow
owner's webhook is posted to as well. Nothing is recorded for a skipped webhook.

The write routes set ``owner_id`` themselves: a body naming another owner is overridden, an update makes the editor
the owner, and the read answers it.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook

from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOKS_URL: str = '/webhooks'
ADMIN_USER_ID: int = 1
ADMIN_GROUP: str = '1'

DENIED_TYPE_ID: int = 98301
OPEN_TYPE_ID: int = 98302
DENIED_OBJECT_ID: int = 98311
OPEN_OBJECT_ID: int = 98312
NARROW_OWNER_ID: int = 98321
INACTIVE_OWNER_ID: int = 98322
NARROW_GROUP_ID: int = 2
MISSING_OWNER_ID: int = 98329

ADMIN_HOOK_ID: int = 98331
NARROW_HOOK_ID: int = 98332
INACTIVE_HOOK_ID: int = 98333
OWNERLESS_HOOK_ID: int = 98334
EDITED_HOOK_ID: int = 98335
DELETED_OWNER_HOOK_ID: int = 98336
ALL_HOOK_IDS: list[int] = [
    ADMIN_HOOK_ID, NARROW_HOOK_ID, INACTIVE_HOOK_ID, OWNERLESS_HOOK_ID, EDITED_HOOK_ID, DELETED_OWNER_HOOK_ID,
]
CREATED_NAME: str = 'Scope Created Hook'

ALL_PERMISSIONS: list[str] = ['CREATE', 'READ', 'UPDATE', 'DELETE']


def _hook_url(webhook_id: int) -> str:
    """Each webhook posts to its own URL, so a POST names its webhook"""
    return f'http://scope-{webhook_id}.test/hook'


def _webhook_doc(webhook_id: int, owner_id: int | None) -> dict[str, Any]:
    """An active DELETE webhook; owner_id None leaves the key out, as a webhook stored before owners did"""
    doc: dict[str, Any] = {'public_id': webhook_id, 'name': f'Scope {webhook_id}', 'url': _hook_url(webhook_id),
                           'event_types': ['DELETE'], 'active': True}
    if owner_id is not None:
        doc['owner_id'] = owner_id

    return doc


@pytest.fixture(name='posted', autouse=True)
def fixture_posted(database_manager: MongoDatabaseManager, database_name: str, monkeypatch: pytest.MonkeyPatch):
    """
    Seeds the types, objects, owners and webhooks, records every POST, and purges it all after

    The delivery runs on the calling thread and the .test hosts are let through the destination check; nothing
    leaves the process
    """
    def _collection(name: str):
        return database_manager.get_collection(name, database_name)

    def _purge() -> None:
        _collection(CmdbType.COLLECTION).delete_many({'public_id': {'$in': [DENIED_TYPE_ID, OPEN_TYPE_ID]}})
        _collection(CmdbObject.COLLECTION).delete_many({'public_id': {'$in': [DENIED_OBJECT_ID, OPEN_OBJECT_ID]}})
        _collection(CmdbUser.COLLECTION).delete_many({'public_id': {'$in': [NARROW_OWNER_ID, INACTIVE_OWNER_ID]}})
        _collection(CmdbWebhook.COLLECTION).delete_many(
            {'$or': [{'public_id': {'$in': ALL_HOOK_IDS}}, {'name': CREATED_NAME}]})
        _collection(CmdbWebhookEvent.COLLECTION).delete_many({'webhook_id': {'$in': ALL_HOOK_IDS}})

    _purge()
    denied_type = make_type_doc(DENIED_TYPE_ID, 'webhook-scope-denied')
    denied_type['acl'] = {'activated': True, 'groups': {'includes': {ADMIN_GROUP: ALL_PERMISSIONS}}}
    _collection(CmdbType.COLLECTION).insert_many([denied_type, make_type_doc(OPEN_TYPE_ID, 'webhook-scope-open')])
    _collection(CmdbObject.COLLECTION).insert_many([
        make_object_doc(DENIED_OBJECT_ID, DENIED_TYPE_ID, [make_field('dg-name', 'denied')]),
        make_object_doc(OPEN_OBJECT_ID, OPEN_TYPE_ID, [make_field('dg-name', 'open')]),
    ])
    _collection(CmdbUser.COLLECTION).insert_many([
        {'public_id': NARROW_OWNER_ID, 'user_name': 'scope-narrow', 'active': True, 'group_id': NARROW_GROUP_ID},
        {'public_id': INACTIVE_OWNER_ID, 'user_name': 'scope-inactive', 'active': False, 'group_id': 1},
    ])
    _collection(CmdbWebhook.COLLECTION).insert_many([
        _webhook_doc(ADMIN_HOOK_ID, ADMIN_USER_ID), _webhook_doc(NARROW_HOOK_ID, NARROW_OWNER_ID),
        _webhook_doc(INACTIVE_HOOK_ID, INACTIVE_OWNER_ID), _webhook_doc(OWNERLESS_HOOK_ID, None),
        _webhook_doc(DELETED_OWNER_HOOK_ID, MISSING_OWNER_ID),
    ])

    posted: list[str] = []

    def _post(url: str, **_kwargs: Any) -> Any:
        posted.append(url)
        return SimpleNamespace(status_code=HTTPStatus.OK)

    monkeypatch.setattr(webhook_helper.DISPATCH_EXECUTOR, 'submit', lambda fn, *args, **kwargs: fn(*args, **kwargs))
    monkeypatch.setattr(webhook_helper, 'refused_destination_reason', lambda *_a, **_k: None)
    monkeypatch.setattr(webhook_helper.requests, 'post', _post)

    yield posted
    _purge()


def _recorded_hook_ids(database_manager: MongoDatabaseManager, database_name: str) -> set[int]:
    """The webhooks a CmdbWebhookEvent was recorded for"""
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)

    return {event['webhook_id'] for event in events.find({'webhook_id': {'$in': ALL_HOOK_IDS}})}


class TestDeliveryScope:
    """DELETE /objects/<id> notifies only the webhooks whose owner may read the object"""

    def test_an_object_of_the_denied_type_reaches_the_admin_webhook_only(
            self, rest_api, posted: list[str], database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The narrow owner's group is left out by the ACL; the inactive, deleted and absent owners receive nothing"""
        assert rest_api.delete(f'/objects/{DENIED_OBJECT_ID}').status_code == HTTPStatus.OK

        assert [url for url in posted if '.test/hook' in url] == [_hook_url(ADMIN_HOOK_ID)]
        assert _recorded_hook_ids(database_manager, database_name) == {ADMIN_HOOK_ID}

    def test_an_object_of_an_open_type_reaches_every_active_owner(
            self, rest_api, posted: list[str], database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The twin: the narrow owner receives what its group may read; the other three still do not"""
        assert rest_api.delete(f'/objects/{OPEN_OBJECT_ID}').status_code == HTTPStatus.OK

        assert sorted(url for url in posted if '.test/hook' in url) == sorted(
            [_hook_url(ADMIN_HOOK_ID), _hook_url(NARROW_HOOK_ID)])
        assert _recorded_hook_ids(database_manager, database_name) == {ADMIN_HOOK_ID, NARROW_HOOK_ID}


class TestTheOwnerIsServerOwned:
    """The write routes set owner_id; the read answers it"""

    def test_create_makes_the_caller_the_owner_whatever_the_body_says(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A body naming another owner cannot widen or redirect the scope"""
        body = {'name': CREATED_NAME, 'url': 'http://created.test/hook', 'event_types': ['CREATE'],
                'owner_id': NARROW_OWNER_ID}

        response = rest_api.post(f'{WEBHOOKS_URL}/', json=body)

        assert response.status_code == HTTPStatus.OK
        stored = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'public_id': response.get_json()})
        assert stored['owner_id'] == ADMIN_USER_ID

    def test_an_update_makes_the_editor_the_owner(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Whoever sets the URL decides where the data goes - also when the body names the old owner"""
        webhooks = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)
        webhooks.insert_one(_webhook_doc(EDITED_HOOK_ID, NARROW_OWNER_ID))
        body = {'name': 'Edited', 'url': _hook_url(EDITED_HOOK_ID), 'event_types': ['DELETE'],
                'owner_id': NARROW_OWNER_ID}

        response = rest_api.put(f'{WEBHOOKS_URL}/{EDITED_HOOK_ID}', json=body)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert webhooks.find_one({'public_id': EDITED_HOOK_ID})['owner_id'] == ADMIN_USER_ID
        assert response.get_json()['result']['owner_id'] == ADMIN_USER_ID

    @pytest.mark.parametrize('webhook_id, owner_id', [
        (NARROW_HOOK_ID, NARROW_OWNER_ID), (OWNERLESS_HOOK_ID, None),
    ], ids=['owned', 'ownerless'])
    def test_the_read_answers_the_owner(self, rest_api, webhook_id: int, owner_id: int | None) -> None:
        """An ownerless webhook answers null"""
        response = rest_api.get(f'{WEBHOOKS_URL}/{webhook_id}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['owner_id'] == owner_id

    def test_the_list_answers_the_owner(self, rest_api) -> None:
        """Every row carries it"""
        rows = rest_api.get(f'{WEBHOOKS_URL}/?limit=0').get_json()['results']

        assert {row['public_id']: row['owner_id'] for row in rows if row['public_id'] in ALL_HOOK_IDS} == {
            ADMIN_HOOK_ID: ADMIN_USER_ID, NARROW_HOOK_ID: NARROW_OWNER_ID,
            INACTIVE_HOOK_ID: INACTIVE_OWNER_ID, OWNERLESS_HOOK_ID: None, DELETED_OWNER_HOOK_ID: MISSING_OWNER_ID,
        }
