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
This module contains the classes of all WebhooksEventManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class WebhooksEventManagerError(Exception):
    """
    Raised to catch all WebhooksEventManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all WebhooksEventManager related errors
        """
        super().__init__(err)

# ------------------------------------------ WebhooksEventManager - ERRORS ------------------------------------------- #

class WebhooksEventManagerInitError(WebhooksEventManagerError):
    """
    Raised when WebhooksEventManager could not be initialised
    """


class WebhooksEventManagerInsertError(WebhooksEventManagerError):
    """
    Raised when WebhooksEventManager could not insert a CmdbWebhookEvent
    """


class WebhooksEventManagerGetError(WebhooksEventManagerError):
    """
    Raised when WebhooksEventManager could not retrieve a CmdbWebhookEvent
    """


class WebhooksEventManagerUpdateError(WebhooksEventManagerError):
    """
    Raised when WebhooksEventManager could not update a CmdbWebhookEvent
    """


class WebhooksEventManagerDeleteError(WebhooksEventManagerError):
    """
    Raised when WebhooksEventManager could not delete a CmdbWebhookEvent
    """


class WebhooksEventManagerIterationError(WebhooksEventManagerError):
    """
    Raised when WebhooksEventManager could not iterate over CmdbWebhookEvents
    """
