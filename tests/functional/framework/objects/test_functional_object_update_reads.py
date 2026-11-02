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
Functional tests: how many reads one object update costs, counted at the driver

An update reads its target once (raw - also the write ledger's snapshot) and once more after the write, and takes
its type from the request's type cache for every step that needs it: the read check, the field validation, the IPAM
and Rack checks, the licence, the write permission and the Rack consequence. The edit logs' renders share the
request's lookups - the type cache and the users - so they read neither the type nor the users again per target; a
bulk delete's logs share theirs the same way. The UPDATE event reads the subscribed webhooks once per request - and,
with one subscribed, the type's ACL and the owners once per request as well. These counts guard against a step
reading again
"""
import json
from collections import Counter
from http import HTTPStatus
from typing import Any, Iterator

import pymongo.collection
import pytest

import cmdb.interface.rest_api.routes.webhook_routes.webhook_helper as webhook_helper
from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook

from tests.functional.framework.objects.objects_route_helpers import (
    BULK_OBJECT_IDS,
    BULK_UPDATED_VALUE,
    NAME_FIELD,
    ROUTE_URL,
    drop_object,
    insert_object_doc,
    object_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

#: Per target: the read before the write and the read after it
OBJECT_READS_PER_TARGET: int = 2
#: Per request: the one read of the targets' shared type (the cache answers every later step and target)
SHARED_TYPE_READS: int = 1
#: Per target: the edit log's render reads no type - it shares the update's type cache
RENDER_TYPE_READS_PER_TARGET: int = 0
#: Per request: the edit logs' renders read the users they name once (author / editor of the targets)
RENDER_USER_READS: int = 1
#: Per request: the caller, read once to resolve the token
TOKEN_USER_READS: int = 1
SEED_VALUE: str = 'seed'
#: Per request: the subscribed webhooks of the operation, one find - no count aggregation
WEBHOOK_READS: int = 1
#: With a subscribed webhook, per request: its owner (one $in) and the targets' type ACL (one find)
SUBSCRIBED_EXTRA_TYPE_READS: int = 1
SUBSCRIBED_WEBHOOK_ID: int = 86201
#: The seeded admin - the subscribed webhook's owner
ADMIN_OWNER_ID: int = 1


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The bulk targets, all of the package's one type"""
    for public_id in BULK_OBJECT_IDS:
        insert_object_doc(database_manager, database_name, public_id, SEED_VALUE)
    yield
    for public_id in BULK_OBJECT_IDS:
        drop_object(database_manager, database_name, public_id)


@pytest.fixture(name='reads')
def fixture_reads(monkeypatch: pytest.MonkeyPatch) -> Counter:
    """Counts every find the driver runs, by collection, and every aggregate as '<collection>:aggregate'"""
    counter: Counter = Counter()
    original_find = pymongo.collection.Collection.find
    original_aggregate = pymongo.collection.Collection.aggregate

    def _counting_find(collection: Any, *args: Any, **kwargs: Any) -> Any:
        counter[collection.name] += 1
        return original_find(collection, *args, **kwargs)

    def _counting_aggregate(collection: Any, *args: Any, **kwargs: Any) -> Any:
        counter[f'{collection.name}:aggregate'] += 1
        return original_aggregate(collection, *args, **kwargs)

    monkeypatch.setattr(pymongo.collection.Collection, 'find', _counting_find)
    monkeypatch.setattr(pymongo.collection.Collection, 'aggregate', _counting_aggregate)

    return counter


@pytest.fixture(name='subscribed_webhook')
def fixture_subscribed_webhook(database_manager: MongoDatabaseManager, database_name: str,
                               monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """An active UPDATE webhook owned by the admin; delivery is stubbed - only the reads are counted"""
    webhooks = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)
    webhooks.insert_one({'public_id': SUBSCRIBED_WEBHOOK_ID, 'name': 'counted', 'url': 'http://hooks.test/h',
                         'event_types': ['UPDATE'], 'active': True, 'owner_id': ADMIN_OWNER_ID})
    monkeypatch.setattr(webhook_helper, 'dispatch_webhook_deliveries', lambda *_args, **_kwargs: None)
    yield
    webhooks.delete_one({'public_id': SUBSCRIBED_WEBHOOK_ID})


def _expected(targets: int) -> tuple[int, int]:
    """The type and object reads of an update of this many targets of one type"""
    return SHARED_TYPE_READS + RENDER_TYPE_READS_PER_TARGET * targets, OBJECT_READS_PER_TARGET * targets


def test_a_single_update_reads_its_type_once(rest_api, reads: Counter) -> None:
    """Every step of the update shares the one type read"""
    target = BULK_OBJECT_IDS[0]

    response = rest_api.put(f'{ROUTE_URL}/{target}', json=object_payload(target, BULK_UPDATED_VALUE))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert (reads[CmdbType.COLLECTION], reads[CmdbObject.COLLECTION]) == _expected(1)


@pytest.mark.parametrize('method', ['put', 'patch'])
def test_a_bulk_update_reads_the_shared_type_once(rest_api, reads: Counter, method: str) -> None:
    """Three targets of one type: one type read for all of them, plus each target's log render"""
    if method == 'put':
        response = rest_api.put(f'{ROUTE_URL}/{BULK_OBJECT_IDS[0]}',
                                json=object_payload(BULK_OBJECT_IDS[0], BULK_UPDATED_VALUE),
                                query_string={'objectIDs': BULK_OBJECT_IDS})
    else:
        response = rest_api.patch(f'{ROUTE_URL}/', json={'fields': [{'name': NAME_FIELD, 'value': BULK_UPDATED_VALUE}]},
                                  query_string={'objectIDs': BULK_OBJECT_IDS})

    assert response.status_code == HTTPStatus.ACCEPTED
    assert (reads[CmdbType.COLLECTION], reads[CmdbObject.COLLECTION]) == _expected(len(BULK_OBJECT_IDS))


def _bulk_put(rest_api) -> Any:
    """A bulk PUT of every seeded target"""
    return rest_api.put(f'{ROUTE_URL}/{BULK_OBJECT_IDS[0]}',
                        json=object_payload(BULK_OBJECT_IDS[0], BULK_UPDATED_VALUE),
                        query_string={'objectIDs': BULK_OBJECT_IDS})


def test_the_webhook_lookup_is_one_find_per_request(rest_api, reads: Counter) -> None:
    """Nothing subscribed: one find for the whole bulk update, and no count aggregation at all"""
    response = _bulk_put(rest_api)

    assert response.status_code == HTTPStatus.ACCEPTED
    assert reads[CmdbWebhook.COLLECTION] == WEBHOOK_READS
    assert reads[f'{CmdbWebhook.COLLECTION}:aggregate'] == 0


@pytest.mark.usefixtures('subscribed_webhook')
def test_a_subscribed_webhook_adds_one_type_acl_read_per_request(rest_api, reads: Counter) -> None:
    """Three events, one webhook find and one type ACL read - not one of each per target"""
    response = _bulk_put(rest_api)
    type_reads, object_reads = _expected(len(BULK_OBJECT_IDS))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert reads[CmdbWebhook.COLLECTION] == WEBHOOK_READS
    assert reads[CmdbType.COLLECTION] == type_reads + SUBSCRIBED_EXTRA_TYPE_READS
    assert reads[CmdbObject.COLLECTION] == object_reads


def test_a_bulk_delete_reads_the_webhooks_once(rest_api, reads: Counter) -> None:
    """The DELETE event of every deleted object shares one webhook lookup"""
    ids: str = ','.join(str(public_id) for public_id in BULK_OBJECT_IDS)

    response = rest_api.delete(f'{ROUTE_URL}/delete/{ids}')

    assert response.status_code == HTTPStatus.OK
    assert reads[CmdbWebhook.COLLECTION] == WEBHOOK_READS
    assert reads[f'{CmdbWebhook.COLLECTION}:aggregate'] == 0


def test_the_edit_logs_read_their_users_once(rest_api, reads: Counter) -> None:
    """Three targets' logs, one user read for all of them - plus the caller's token"""
    response = _bulk_put(rest_api)

    assert response.status_code == HTTPStatus.ACCEPTED
    assert reads[CmdbUser.COLLECTION] == TOKEN_USER_READS + RENDER_USER_READS


def test_a_bulk_delete_reads_its_logs_users_once(rest_api, reads: Counter) -> None:
    """The deletion logs of every target share one render lookup"""
    ids: str = ','.join(str(public_id) for public_id in BULK_OBJECT_IDS)

    response = rest_api.delete(f'{ROUTE_URL}/delete/{ids}')

    assert response.status_code == HTTPStatus.OK
    assert reads[CmdbUser.COLLECTION] == TOKEN_USER_READS + RENDER_USER_READS


def test_a_shared_render_stores_the_same_log_as_a_single_update(rest_api, database_manager: MongoDatabaseManager,
                                                                database_name: str) -> None:
    """The bulk update's logs (shared lookups) carry the render a single update's log (its own) carries"""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    single, bulk = BULK_OBJECT_IDS[0], BULK_OBJECT_IDS[1]
    logs.delete_many({'object_id': {'$in': BULK_OBJECT_IDS}})

    rest_api.put(f'{ROUTE_URL}/{single}', json=object_payload(single, BULK_UPDATED_VALUE))
    _bulk_put(rest_api)

    def _render_state(public_id: int) -> dict[str, Any]:
        entry = logs.find_one({'object_id': public_id, 'action_name': LogAction.EDIT.name},
                              sort=[('public_id', 1)])
        raw: Any = entry['render_state']
        state: dict[str, Any] = json.loads(raw.decode('UTF-8') if isinstance(raw, bytes) else raw)
        return {key: state[key] for key in ('type_information', 'sections')}

    try:
        assert _render_state(single)['type_information'] == _render_state(bulk)['type_information']
        assert _render_state(single)['sections'] == _render_state(bulk)['sections']
    finally:
        logs.delete_many({'object_id': {'$in': BULK_OBJECT_IDS}})


#: A delete, single or bulk of one type: the type is read once and handed to every check, clean-up and log
DELETE_TYPE_READS: int = 1


def test_a_single_delete_reads_its_type_once(rest_api, reads: Counter) -> None:
    """The licence, the IPAM guards, the Rack clean-up and the deletion log all take the route's one read"""
    response = rest_api.delete(f'{ROUTE_URL}/{BULK_OBJECT_IDS[0]}')

    assert response.status_code == HTTPStatus.OK
    assert reads[CmdbType.COLLECTION] == DELETE_TYPE_READS


def test_a_bulk_delete_reads_the_selections_type_once(rest_api, reads: Counter) -> None:
    """The selection's one lookup answers every target's checks, clean-up and log"""
    ids: str = ','.join(str(public_id) for public_id in BULK_OBJECT_IDS)

    response = rest_api.delete(f'{ROUTE_URL}/delete/{ids}')

    assert response.status_code == HTTPStatus.OK
    assert reads[CmdbType.COLLECTION] == DELETE_TYPE_READS

