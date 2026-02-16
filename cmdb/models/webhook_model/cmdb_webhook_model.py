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
This module contains the implementation of CmdbWebhook, which is representing
a webhook in Datagarry
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbWebhook - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbWebhook(CmdbDAO):
    """
    Implementation of CmdbWebhook

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.webhooks'
    MODEL = 'Webhook'
    DEFAULT_VERSION: str = '1.0.0'
    REQUIRED_INIT_KEYS: list[str] = [
        'name',
        'url',
        'event_types',
        'active',
    ]

    SCHEMA: dict[str, Any] = {
        'public_id': {
            'type': 'integer'
        },
        'name': {
            'type': 'string',
            'required': True,
        },
        'url': {
            'type': 'string',
            'required': True,
        },
        'event_types': {
            'type': 'list',
            'required': True,
        },
        'active': {
            'type': 'boolean',
            'default': True
        },
    }

# ---------------------------------------------------- CONSTRUCTOR --------------------------------------------------- #

    def __init__(
            self,
            name:str,
            url: str,
            event_types: list,
            active: bool,
            **kwargs):
        """
        Initializes a new instance of the CmdbWebhook class, representing a webhook configuration

        Args:
            name (str): Human-readable name of the webhook
            url (str): URL endpoint where the webhook will send events
            event_types (list): List of WebhookEventType values that the webhook listens for
            active (bool): Whether the webhook is currently active and should receive events
            **kwargs: Additional fields to pass to the superclass initializer
        """
        self.name = name
        self.url = url
        self.event_types = event_types
        self.active = active

        super().__init__(**kwargs)

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbWebhook":
        """
        Convert data to instance of CmdbWebhook
        """
        return cls(
            public_id=data.get('public_id'),
            name=data.get('name'),
            url=data.get('url'),
            event_types=data.get('event_types'),
            active=data.get('active'),
        )


    @classmethod
    def to_json(cls, instance: "CmdbWebhook") -> dict:
        """Convert a CmdbWebhook instance to json conform data"""
        return {
            'public_id': instance.get_public_id(),
            'name': instance.name,
            'url': instance.url,
            'event_types': instance.event_types,
            'active': instance.active,
        }
