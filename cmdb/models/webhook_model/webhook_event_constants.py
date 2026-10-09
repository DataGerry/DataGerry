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
Document keys of a CmdbWebhookEvent (collection ``framework.webhookEvents``)

Named here so the routes that read the delivery log, and the masking of the object values in it, spell the keys
the model stores
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'OBJECT_VALUE_KEYS',
    'WEBHOOK_EVENT_SUMMARY_KEYS',
    'WebhookEventKey',
]


class WebhookEventKey(BaseStrEnum):
    """Document field names of a CmdbWebhookEvent"""
    PUBLIC_ID = 'public_id'
    EVENT_TIME = 'event_time'
    OPERATION = 'operation'
    WEBHOOK_ID = 'webhook_id'
    OBJECT_BEFORE = 'object_before'
    OBJECT_AFTER = 'object_after'
    CHANGES = 'changes'
    RESPONSE_CODE = 'response_code'
    STATUS = 'status'


# The keys of an event that carry the object's field values - both snapshots and the field-level diff
OBJECT_VALUE_KEYS: tuple[WebhookEventKey, ...] = (
    WebhookEventKey.OBJECT_BEFORE,
    WebhookEventKey.OBJECT_AFTER,
    WebhookEventKey.CHANGES,
)

# What a row of the event LIST carries: every scalar key, none of the object values. The single read answers the
# whole event; the list leaves out the snapshots no table shows, so a page costs scalars rather than documents
WEBHOOK_EVENT_SUMMARY_KEYS: tuple[WebhookEventKey, ...] = (
    WebhookEventKey.PUBLIC_ID,
    WebhookEventKey.WEBHOOK_ID,
    WebhookEventKey.OPERATION,
    WebhookEventKey.EVENT_TIME,
    WebhookEventKey.STATUS,
    WebhookEventKey.RESPONSE_CODE,
)
