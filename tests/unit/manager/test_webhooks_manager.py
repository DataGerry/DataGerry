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
Unit tests for WebhooksManager.get_subscribed_webhooks - the read every object write's event makes

One find (no count aggregation), filtered to active webhooks subscribed to the operation, in public_id order; a read
failure or a stored webhook the model cannot read is the manager's iterate error
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.webhooks_manager import WebhooksManagerIterationError
from cmdb.manager.webhooks_manager import WebhooksManager
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOK_DOCUMENT: dict = {'public_id': 1, 'name': 'hook', 'url': 'http://a.test/h', 'event_types': ['UPDATE'],
                          'active': True, 'owner_id': 1}


def _manager() -> WebhooksManager:
    """A WebhooksManager over a mocked database manager"""
    return WebhooksManager(MagicMock())


def test_one_find_with_the_subscription_filter_in_id_order() -> None:
    """No count - the total was never used"""
    manager = _manager()

    with patch.object(manager, 'find', return_value=[WEBHOOK_DOCUMENT]) as find, \
         patch.object(manager, 'aggregate_within_time_limit') as count:
        found = manager.get_subscribed_webhooks(WebhookEventType.UPDATE)

    find.assert_called_once_with(
        {'$and': [{'active': True}, {'event_types': WebhookEventType.UPDATE}]}, sort=[('public_id', 1)],
    )
    count.assert_not_called()
    assert [webhook.public_id for webhook in found] == [1]
    assert isinstance(found[0], CmdbWebhook)


def test_no_subscribed_webhook_is_an_empty_list() -> None:
    """The common case on every object write"""
    manager = _manager()

    with patch.object(manager, 'find', return_value=[]):
        assert not manager.get_subscribed_webhooks(WebhookEventType.CREATE)


def test_a_failed_read_is_the_iterate_error() -> None:
    """Carrying the database's error"""
    manager = _manager()
    failure = BaseManagerGetError('lost')

    with patch.object(manager, 'find', side_effect=failure), pytest.raises(WebhooksManagerIterationError) as caught:
        manager.get_subscribed_webhooks(WebhookEventType.UPDATE)

    assert caught.value.args[0] is failure
