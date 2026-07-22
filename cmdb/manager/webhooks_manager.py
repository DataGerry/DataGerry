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
<<<<<<< HEAD
from typing import Any
import json
from datetime import datetime, timezone
import requests
=======
>>>>>>> origin/version-3.2

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook

from cmdb.errors.manager import (
    BaseManagerInitError,
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)
<<<<<<< HEAD
=======

# Webhooks have no dedicated manager-error hierarchy yet (see discussion backlog); the shared
# BaseManager errors are used so this manager can run on GenericManager
WEBHOOKS_MANAGER_ERRORS: dict[str, type[Exception]] = {
    'init': BaseManagerInitError,
    'insert': BaseManagerInsertError,
    'get': BaseManagerGetError,
    'update': BaseManagerUpdateError,
    'delete': BaseManagerDeleteError,
    'iterate': BaseManagerIterationError,
}
>>>>>>> origin/version-3.2

# -------------------------------------------------------------------------------------------------------------------- #
#                                                WebhooksManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class WebhooksManager(GenericManager):
    """
    The WebhooksManager manages the interaction between CmdbWebhooks and the database

<<<<<<< HEAD
    def __init__(self, dbm: MongoDatabaseManager, database:str = None) -> None:
        """
        Set the database connection and the queue for sending events

        Args:
            dbm (MongoDatabaseManager): Database connection
        """
        self.webhooks_event_manager = WebhooksEventManager(dbm, database)

        super().__init__(CmdbWebhook.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_webhook(self, data: dict) -> int:
        """
        Inserts a single CmdbWebhook in the database

        Args:
            data (dict): Data of the new CmdbWebhook

        Returns:
            int: public_id of the newly created CmdbWebhook
        """
        try:
            new_webhook = CmdbWebhook(**data)

            ack = self.insert(new_webhook.__dict__)

            return ack
            #TODO: ERROR-FIX
        except Exception as err:
            raise BaseManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_webhook(self, public_id: int) -> CmdbWebhook:
        """
        Retrives a CmdbWebhook from the database with the given public_id

        Args:
            public_id (int): public_id of the CmdbWebhook which should be retrieved
        Raises:
            BaseManagerGetError: Raised if the CmdbWebhook could not be retrieved
        Returns:
            CmdbWebhook: The requested CmdbWebhook if it exists, else None
        """
        try:
            requested_webhook = self.get_one(public_id)
        except Exception as err:
            #TODO: ERROR-FIX
            raise BaseManagerGetError(f"Webhook with ID: {public_id}! 'GET' Error: {err}") from err

        if requested_webhook:
            requested_webhook: CmdbWebhook = CmdbWebhook.from_data(requested_webhook)

            return requested_webhook

        #TODO: ERROR-FIX
        raise BaseManagerGetError(f'Webhook with ID: {public_id} not found!')


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbWebhook]:
        """
        Performs an aggregation on the database

        Args:
            builder_params (BuilderParameters): Contains input to identify the target of action

        Raises:
            BaseManagerIterationError: Raised when something goes wrong during the aggregate part
            BaseManagerIterationError: Raised when something goes wrong during the building of the IterationResult
        Returns:
            IterationResult[CmdbWebhook]: Result which matches the Builderparameters
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[CmdbWebhook] = IterationResult(aggregation_result, total)
            iteration_result.convert_to(CmdbWebhook)

            return iteration_result
        except Exception as err:
            #TODO: ERROR-FIX
            raise BaseManagerIterationError(err) from err

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

    #TODO: REFACTOR-FIX (move method to WebhookEventManager)
    def send_webhook_event(
            self,
            operation: WebhookEventType = None,
            object_before: dict = None,
            object_after: dict = None,
            changes: dict = None
        ) -> None:
        """
        Sends a webhook event to all configured webhook endpoints that are subscribed 
        to the specified operation type.

        Args:
            operation (WebhookEventType, optional): The type of event operation (e.g., create, update, delete)
                                                    triggering the webhook
            object_before (dict, optional): The state of the object before the change (for update/delete operations)
            object_after (dict, optional): The state of the object after the change (for create/update operations)
            changes (dict, optional): Dictionary detailing the specific changes between object_before and object_after
        """
        try:
            builder_params = BuilderParameters({})
            webhooks: IterationResult[CmdbWebhook] = self.iterate(builder_params).results

            if not webhooks:
                return

            webhook: CmdbWebhook
            for webhook in webhooks:
                if not webhook.active:
                    continue

                # Check if operation is registered in the webhook
                if operation not in webhook.event_types:
                    continue

                payload = self.build_payload(operation, object_before, object_after, changes)

                response: requests.Response = requests.post(
                    webhook.url,
                    data=json.dumps(payload, default=default, ensure_ascii=False, indent=2),
                    headers={'Content-Type': 'application/json'},
                    timeout=3,
                )

                payload.update({
                    'public_id': self.webhooks_event_manager.get_next_public_id(inc_id=True),
                    'webhook_id': webhook.public_id,
                    'response_code': response.status_code,
                    'status': response.status_code == 200
                })

                self.webhooks_event_manager.insert_webhook_event(payload)
        except Exception as err:
            LOGGER.error("[send_webhook_event] Exception: %s, Type: %s", str(err), type(err))


    def build_payload(
            self,
            operation: WebhookEventType,
            object_before: dict,
            object_after:dict,
            changes: dict = None
        ) -> dict[str, Any]:
        """
        Constructs the payload dictionary for a webhook event

        Args:
            operation (WebhookEventType): The type of operation that triggered the webhook event
            object_before (dict): The object's state before the event occurred
            object_after (dict): The object's state after the event occurred
            changes (dict, optional): A dictionary summarizing the changes made to the object

        Returns:
            dict[str, Any]: A dictionary containing event metadata and object data to be sent to webhook endpoints
        """
        return {
            'event_time': datetime.now(timezone.utc),
            'operation': operation,
            'object_before': object_before,
            'object_after': object_after,
            'changes': changes,
        }
=======
    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, CmdbWebhook, WEBHOOKS_MANAGER_ERRORS, database)
>>>>>>> origin/version-3.2
