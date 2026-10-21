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
Integration tests of the delivery-log list pipeline against a real collection

The criteria the list route builds (``build_event_list_criteria``) run through the real manager: the database answers
documents without ``object_before`` / ``object_after`` / ``changes`` - trimmed in the pipeline, not in Python - while
the object-ACL mask still runs first, a caller stage still matches a snapshot value, and paging and the total count
are unchanged
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.webhooks_event_manager import WebhooksEventManager
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.webhook_event_constants import OBJECT_VALUE_KEYS, WEBHOOK_EVENT_SUMMARY_KEYS
from cmdb.interface.rest_api.routes.webhook_routes.webhook_event_access import build_event_masking_stage
from cmdb.interface.rest_api.routes.webhook_routes.webhook_event_summary import build_event_list_criteria
# -------------------------------------------------------------------------------------------------------------------- #

DENIED_TYPE_ID: int = 98301
ALLOWED_TYPE_ID: int = 98302
DENIED_EVENT_ID: int = 98311
ALLOWED_EVENT_ID: int = 98312
EVENT_IDS: list[int] = [DENIED_EVENT_ID, ALLOWED_EVENT_ID]
PLAIN_VALUE: str = 'readable'
SECRET_VALUE: str = 'masked-first'
PAGE_SIZE: int = 1


def _event(public_id: int, type_id: int, value: str) -> dict[str, Any]:
    """An UPDATE delivery of an object of the given type."""
    snapshot = {'public_id': public_id, 'type_id': type_id, 'fields': [{'name': 'a', 'value': value}]}

    return {'public_id': public_id, 'event_time': None, 'operation': 'UPDATE', 'webhook_id': 1,
            'object_before': snapshot, 'object_after': snapshot, 'changes': {'a': value},
            'response_code': 200, 'status': True}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[WebhooksEventManager]:
    """A real events manager over two seeded events; removed afterwards."""
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)
    events.delete_many({'public_id': {'$in': EVENT_IDS}})
    events.insert_many([_event(DENIED_EVENT_ID, DENIED_TYPE_ID, SECRET_VALUE),
                        _event(ALLOWED_EVENT_ID, ALLOWED_TYPE_ID, PLAIN_VALUE)])

    yield WebhooksEventManager(database_manager)

    events.delete_many({'public_id': {'$in': EVENT_IDS}})


def _iterate(manager: WebhooksEventManager, caller: list[dict[str, Any]], limit: int = 0) -> tuple[list[Any], int]:
    """Runs the list's criteria - mask on the denied type, the caller's stages, the summary - through the manager."""
    own: list[dict[str, Any]] = [{'$match': {'public_id': {'$in': EVENT_IDS}}}, *caller]
    criteria = build_event_list_criteria(build_event_masking_stage([DENIED_TYPE_ID]), own)

    return manager.iterate_query(BuilderParameters(criteria=criteria, limit=limit, sort='public_id', order=1))


def test_the_database_answers_the_summary_only(manager: WebhooksEventManager) -> None:
    """No object value reaches Python, for a masked or a readable event"""
    documents, total = _iterate(manager, [])

    assert total == len(EVENT_IDS)
    assert all(set(document) == {key.value for key in WEBHOOK_EVENT_SUMMARY_KEYS} for document in documents)
    assert not {key.value for key in OBJECT_VALUE_KEYS} & {key for document in documents for key in document}


def test_the_mask_still_runs_before_a_caller_stage(manager: WebhooksEventManager) -> None:
    """A caller stage matches a readable value, and cannot find the masked one"""
    readable, _total = _iterate(manager, [{'$match': {'object_after.fields.value': PLAIN_VALUE}}])
    secret, _total = _iterate(manager, [{'$match': {'object_after.fields.value': SECRET_VALUE}}])

    assert [document['public_id'] for document in readable] == [ALLOWED_EVENT_ID]
    assert not secret


def test_paging_and_the_total_are_unchanged(manager: WebhooksEventManager) -> None:
    """A one-row page, the total still counting both"""
    documents, total = _iterate(manager, [], limit=PAGE_SIZE)

    assert [document['public_id'] for document in documents] == [DENIED_EVENT_ID]
    assert total == len(EVENT_IDS)
