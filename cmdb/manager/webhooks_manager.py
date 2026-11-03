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
This module contains the implementation of the WebhooksManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.webhook_constants import WebhookKey

from cmdb.errors.manager import BaseManagerGetError

from cmdb.errors.manager.webhooks_manager import WEBHOOKS_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                WebhooksManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class WebhooksManager(GenericManager):
    """
    The WebhooksManager manages the interaction between CmdbWebhooks and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, CmdbWebhook, WEBHOOKS_MANAGER_ERRORS, database)


    def get_subscribed_webhooks(self, operation: str) -> list[CmdbWebhook]:
        """
        Reads the active CmdbWebhooks subscribed to one operation - one find, no count

        Called on every object write that may emit an event, so it reads exactly what the fan-out needs: the
        matching webhooks, no total

        Args:
            operation (str): The WebhookEventType value of the write (CREATE / UPDATE / DELETE)

        Raises:
            Exception: The configured 'iterate' exception when the read fails or a stored webhook does not fit the
                model

        Returns:
            list[CmdbWebhook]: The subscribed active webhooks, in public_id order
        """
        criteria: dict[str, Any] = {
            '$and': [{WebhookKey.ACTIVE.value: True}, {WebhookKey.EVENT_TYPES.value: operation}],
        }

        try:
            documents: list[dict[str, Any]] = self.find(criteria, sort=[(WebhookKey.PUBLIC_ID.value, 1)])

            return [CmdbWebhook.from_data(document) for document in documents]
        except (BaseManagerGetError, *self._model_errors()) as err:
            LOGGER.error("[get_subscribed_webhooks] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("iterate", Exception)(err) from err
