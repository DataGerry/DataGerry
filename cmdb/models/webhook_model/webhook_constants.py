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
Document keys of a CmdbWebhook (collection ``framework.webhooks``)

In the model layer so the model itself, its routes and the updaters spell the keys the same way; the routes import
the enum from here
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'WebhookKey',
]


class WebhookKey(BaseStrEnum):
    """
    Keys of a CmdbWebhook document, as ``CmdbWebhook.from_data`` reads and ``to_json`` writes them and the webhook
    routes read or set them
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    URL = 'url'
    EVENT_TYPES = 'event_types'
    ACTIVE = 'active'
    #: The user who last saved the webhook - server-owned, it decides which objects the webhook may receive
    OWNER_ID = 'owner_id'
