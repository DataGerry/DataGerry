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
This module provides all errors for the WebhooksEventManager
"""
from typing import Any

from .webhooks_event_manager_errors import (
    WebhooksEventManagerError,
    WebhooksEventManagerInitError,
    WebhooksEventManagerInsertError,
    WebhooksEventManagerGetError,
    WebhooksEventManagerUpdateError,
    WebhooksEventManagerDeleteError,
    WebhooksEventManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'WebhooksEventManagerError',
    'WebhooksEventManagerInitError',
    'WebhooksEventManagerInsertError',
    'WebhooksEventManagerGetError',
    'WebhooksEventManagerUpdateError',
    'WebhooksEventManagerDeleteError',
    'WebhooksEventManagerIterationError',
    'WEBHOOKS_EVENT_MANAGER_ERRORS',
]


WEBHOOKS_EVENT_MANAGER_ERRORS: dict[str, Any] = {
    "init": WebhooksEventManagerInitError,
    "insert": WebhooksEventManagerInsertError,
    "get": WebhooksEventManagerGetError,
    "update": WebhooksEventManagerUpdateError,
    "delete": WebhooksEventManagerDeleteError,
    "iterate": WebhooksEventManagerIterationError,
}
