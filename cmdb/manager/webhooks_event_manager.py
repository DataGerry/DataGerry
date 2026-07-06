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

# WebhookEvents share the BaseManager errors (no dedicated hierarchy yet, see discussion backlog) so
# this manager can run on GenericManager
WEBHOOK_EVENT_MANAGER_ERRORS: dict[str, type[Exception]] = {
    'init': BaseManagerInitError,
    'insert': BaseManagerInsertError,
    'get': BaseManagerGetError,
    'update': BaseManagerUpdateError,
    'delete': BaseManagerDeleteError,
    'iterate': BaseManagerIterationError,
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                             WebhooksEventManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class WebhooksEventManager(GenericManager):
    """
    The WebhooksEventManager manages the interaction between CmdbWebhookEvents and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, CmdbWebhookEvent, WEBHOOK_EVENT_MANAGER_ERRORS, database)
