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
Integration tests for the CmdbWebhook write contract against a real MongoDB

``parse_webhook_params`` is the one place a webhook write is validated and normalised. Two properties
only the stored document can show are pinned here:

- a webhook written through the normalisation satisfies its own ``CmdbWebhook.SCHEMA`` when it is read
  back from the collection
- a webhook written WITHOUT an ``active`` flag is found by the query ``send_webhook_event`` delivers
  through (active + subscribed operation) - it used to be stored switched off and never fire
"""
from typing import Any

import pytest
from cerberus import Validator  # type: ignore

from cmdb.database import MongoDatabaseManager
from cmdb.manager.webhooks_manager import WebhooksManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import parse_webhook_params
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOK_ID_WITHOUT_ACTIVE: int = 97901
WEBHOOK_ID_INACTIVE: int = 97902
WEBHOOK_ID_FOR_SCHEMA: int = 97903

SEED_WEBHOOK_IDS: list[int] = [WEBHOOK_ID_WITHOUT_ACTIVE, WEBHOOK_ID_INACTIVE, WEBHOOK_ID_FOR_SCHEMA]

TARGET_URL: str = 'https://example.test/hook'


def _collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the webhook collection bound to the test database."""
    return database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)


@pytest.fixture(autouse=True)
def _cleanup_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the webhooks seeded by a test, before and after each test."""
    _collection(database_manager, database_name).delete_many({'public_id': {'$in': SEED_WEBHOOK_IDS}})
    yield
    _collection(database_manager, database_name).delete_many({'public_id': {'$in': SEED_WEBHOOK_IDS}})


@pytest.fixture(name='webhooks_manager')
def fixture_webhooks_manager(database_manager: MongoDatabaseManager) -> WebhooksManager:
    """Provides a WebhooksManager wired to the test database."""
    return WebhooksManager(database_manager)


def _store_normalised(webhooks_manager: WebhooksManager, public_id: int, payload: dict[str, Any]) -> None:
    """Runs a raw write payload through parse_webhook_params and inserts it, as the create route does."""
    parse_webhook_params(payload)
    payload['public_id'] = public_id

    webhooks_manager.insert_item(CmdbWebhook.from_data(payload))


def _delivery_ids(webhooks_manager: WebhooksManager, operation: WebhookEventType) -> set[int]:
    """public_ids of the webhooks the delivery query of send_webhook_event finds for an operation"""
    builder_params = BuilderParameters({'$and': [{'active': True}, {'event_types': operation}]})

    return {webhook.public_id for webhook in webhooks_manager.iterate_items(builder_params).results}


class TestActiveDefault:
    """A webhook written without an active flag delivers."""

    def test_a_webhook_without_active_is_found_by_the_delivery_query(self, webhooks_manager: WebhooksManager) -> None:
        """Left out, the flag is the schema default True - the webhook is picked up for its operation"""
        _store_normalised(webhooks_manager, WEBHOOK_ID_WITHOUT_ACTIVE,
                          {'name': 'No flag', 'url': TARGET_URL, 'event_types': ['CREATE']})

        assert WEBHOOK_ID_WITHOUT_ACTIVE in _delivery_ids(webhooks_manager, WebhookEventType.CREATE)

    def test_an_inactive_webhook_is_not_delivered_to(self, webhooks_manager: WebhooksManager) -> None:
        """The explicit false still switches it off - the default applies only to a missing flag"""
        _store_normalised(webhooks_manager, WEBHOOK_ID_INACTIVE,
                          {'name': 'Off', 'url': TARGET_URL, 'event_types': ['CREATE'], 'active': 'false'})

        assert WEBHOOK_ID_INACTIVE not in _delivery_ids(webhooks_manager, WebhookEventType.CREATE)


class TestStoredDocumentSatisfiesTheSchema:
    """What the normalisation stores is a document its own schema accepts."""

    @pytest.mark.parametrize('payload', [
        {'name': ' Typed ', 'url': TARGET_URL, 'event_types': ['CREATE', 'DELETE'], 'active': True},
        {'name': 'Text', 'url': TARGET_URL, 'event_types': '["UPDATE"]', 'active': 'TRUE'},
    ], ids=['json-body', 'query-string'])
    def test_the_read_back_document_validates(self, webhooks_manager: WebhooksManager,
                                              database_manager: MongoDatabaseManager, database_name: str,
                                              payload: dict[str, Any]) -> None:
        """Typed (a JSON body) or text (a query string) in, the same typed document out"""
        _store_normalised(webhooks_manager, WEBHOOK_ID_FOR_SCHEMA, payload)

        stored = _collection(database_manager, database_name).find_one(
            {'public_id': WEBHOOK_ID_FOR_SCHEMA}, {'_id': 0}
        )

        validator = Validator(CmdbWebhook.SCHEMA)
        assert validator.validate(stored), validator.errors
        assert isinstance(stored['event_types'], list)
        assert stored['active'] is True
