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
This module contains the implementation of the WebhooksEventManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.webhook_event_constants import WebhookEventKey

from cmdb.errors.manager import BaseManagerDeleteError
from cmdb.errors.manager.webhooks_event_manager import WEBHOOKS_EVENT_MANAGER_ERRORS, WebhooksEventManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             WebhooksEventManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class WebhooksEventManager(GenericManager):
    """
    The WebhooksEventManager manages the interaction between CmdbWebhookEvents and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Binds the manager to the webhook-event collection of the given database

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): The tenant database in cloud mode, None for the configured one
        """
        super().__init__(dbm, CmdbWebhookEvent, WEBHOOKS_EVENT_MANAGER_ERRORS, database)


    def delete_events_of_webhook(self, webhook_id: int) -> int:
        """
        Deletes every CmdbWebhookEvent a CmdbWebhook produced, in one statement

        Args:
            webhook_id (int): public_id of the CmdbWebhook whose delivery log is removed

        Raises:
            WebhooksEventManagerDeleteError: When the delete fails

        Returns:
            int: How many events were deleted
        """
        try:
            return self.delete_many({WebhookEventKey.WEBHOOK_ID.value: webhook_id}).deleted_count
        except BaseManagerDeleteError as err:
            raise WebhooksEventManagerDeleteError(err) from err
