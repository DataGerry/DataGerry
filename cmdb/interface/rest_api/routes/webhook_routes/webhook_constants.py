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
Shared constants for the CmdbWebhook and CmdbWebhookEvent REST routes

Besides the ACL rights this module owns the delivery constants used by ``webhook_helper``: the
outbound request timeout, the response-code range that counts as delivered, the placeholder code
recorded when there was no HTTP response at all, and the URL schemes a CmdbWebhook may target
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'WebhookRight',
    'WEBHOOK_REQUEST_TIMEOUT_SECONDS',
    'WEBHOOK_DELIVERED_STATUS_MIN',
    'WEBHOOK_DELIVERED_STATUS_MAX',
    'WEBHOOK_NO_RESPONSE_CODE',
    'WEBHOOK_ALLOWED_URL_SCHEMES',
    'WEBHOOK_DISPATCH_MAX_WORKERS',
    'WEBHOOK_DISPATCH_THREAD_PREFIX',
]

#: Seconds to wait for a webhook target before giving up on one delivery
WEBHOOK_REQUEST_TIMEOUT_SECONDS: int = 3

#: Inclusive lower and exclusive upper bound of the response codes that count as a delivery. Any 2xx
#: means the target accepted the payload - a receiver answering 201/202/204 is NOT a failure
WEBHOOK_DELIVERED_STATUS_MIN: int = 200
WEBHOOK_DELIVERED_STATUS_MAX: int = 300

#: Recorded as the response_code of a CmdbWebhookEvent when the request never produced an HTTP
#: response at all (timeout, DNS failure, refused connection, unusable URL). Kept an int because the
#: stored document, its schema and the frontend's log table all type response_code as a number
WEBHOOK_NO_RESPONSE_CODE: int = 0

#: URL schemes a CmdbWebhook may target. A webhook is fetched by the server, so the scheme is not a
#: cosmetic detail - anything outside this set is refused when the webhook is created or updated
WEBHOOK_ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({'http', 'https'})

#: Size of the shared pool that delivers webhooks off the request thread, and its thread-name prefix
WEBHOOK_DISPATCH_MAX_WORKERS: int = 4
WEBHOOK_DISPATCH_THREAD_PREFIX: str = 'webhook-dispatch'


class WebhookRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbWebhook and CmdbWebhookEvent REST routes

    The four rights come from ``WebhookRight`` in cmdb.models.right_model.framework_rights, which puts
    them under ``base.framework.webhook``. There is no separate right for a CmdbWebhookEvent: an event
    is the delivery log of a webhook, so reading one needs VIEW and deleting one needs DELETE - the
    same rights that guard the webhook it belongs to
    """
    ADD = 'base.framework.webhook.add'
    VIEW = 'base.framework.webhook.view'
    EDIT = 'base.framework.webhook.edit'
    DELETE = 'base.framework.webhook.delete'
