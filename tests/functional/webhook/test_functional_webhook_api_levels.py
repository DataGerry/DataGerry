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
Which channel may reach the webhook routes in hosted cloud mode

The definitions are ``ApiLevel.ADMIN``: an ADMIN-level API key (Basic + ``x-api-key``) manages them. The delivery
log is ``ApiLevel.LOCKED``: the same key is refused on all three of its routes, and a refused delete deletes
nothing. The refusal binds that channel only - a Bearer token, which is how the DataGerry frontend calls, reads the
log, because ``verify_api_access`` checks no level for one. On-premise no level is checked at all. The portal is
stubbed
"""
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface import route_utils
from cmdb.interface.route_utils import API_KEY_HEADER
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOKS_URL: str = '/webhooks/'
EVENTS_URL: str = '/webhook_events/'

USER_ID: int = 93981
EVENT_ID: int = 93982
EMAIL: str = 'cloud-webhook-levels@x.io'
PASSWORD: str = 'portal-password'
API_KEY: str = 'subscription-key'
LEVEL_REFUSAL: str = 'No permission for this action!'
ADMIN_GROUP_ID: int = 1

API_KEY_ENVIRON: str = f'HTTP_{API_KEY_HEADER.upper().replace("-", "_")}'


def _portal_user(database: str) -> dict[str, Any]:
    """The ServicePortal's answer: an ADMIN-level subscription on the test database."""
    return {
        'email': EMAIL, 'user_name': 'cloud-webhook-levels', 'password': PASSWORD, 'api_level': ApiLevel.ADMIN,
        'subscriptions': [{'id': 1, 'name': 'sub', 'database': database, 'api_level': ApiLevel.ADMIN,
                           'config_item_limit': 100}],
    }


def _event_doc() -> dict[str, Any]:
    """One delivery of webhook 1."""
    return {
        'public_id': EVENT_ID, 'event_time': None, 'operation': 'CREATE', 'webhook_id': 1,
        'object_before': None, 'object_after': {'public_id': 5}, 'changes': None,
        'response_code': 200, 'status': True,
    }


@pytest.fixture(name='events')
def fixture_events(database_manager: MongoDatabaseManager, database_name: str):
    """One stored delivery, removed afterwards; yields the collection."""
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)
    events.delete_many({'public_id': EVENT_ID})
    events.insert_one(_event_doc())
    yield events
    events.delete_many({'public_id': EVENT_ID})


@pytest.fixture(name='cloud')
def fixture_cloud(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                  database_name: str, events):
    """A hosted-cloud app, a stored tenant admin and a portal that accepts it at ADMIN level."""
    del events
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})
    users.insert_one({
        'public_id': USER_ID, 'user_name': 'cloud-webhook-levels', 'email': EMAIL, 'active': True,
        'group_id': ADMIN_GROUP_ID, 'database': database_name, 'api_level': ApiLevel.ADMIN,
        'registration_time': datetime.now(timezone.utc),
    })

    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    portal = _portal_user(database_name)
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal)

    yield

    users.delete_many({'public_id': USER_ID})


def _api_key_environ() -> dict[str, str]:
    """Basic credentials and the subscription's API key - the cloud API channel."""
    basic: str = base64.b64encode(f'{EMAIL}:{PASSWORD}'.encode('utf-8')).decode('utf-8')

    return {'HTTP_AUTHORIZATION': f'Basic {basic}', API_KEY_ENVIRON: API_KEY}


@pytest.mark.usefixtures('cloud')
class TestTheApiKeyChannel:
    """Basic + x-api-key at ADMIN level."""

    def test_the_definitions_are_reachable(self, rest_api) -> None:
        """ApiLevel.ADMIN: an ADMIN key lists the webhooks"""
        assert rest_api.get(WEBHOOKS_URL, environ_overrides=_api_key_environ()).status_code == HTTPStatus.OK

    @pytest.mark.parametrize('method, url', [
        ('get', EVENTS_URL), ('get', f'{EVENTS_URL}{EVENT_ID}'), ('delete', f'{EVENTS_URL}{EVENT_ID}'),
    ], ids=['list', 'read', 'delete'])
    def test_the_delivery_log_is_refused(self, rest_api, method: str, url: str) -> None:
        """ApiLevel.LOCKED: every log route answers 403, whatever the key's level"""
        response = getattr(rest_api, method)(url, environ_overrides=_api_key_environ())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == LEVEL_REFUSAL

    def test_a_refused_delete_deletes_nothing(self, rest_api, events) -> None:
        """The refusal comes before the route body"""
        rest_api.delete(f'{EVENTS_URL}{EVENT_ID}', environ_overrides=_api_key_environ())

        assert events.count_documents({'public_id': EVENT_ID}) == 1


@pytest.mark.usefixtures('cloud')
class TestTheTokenChannel:
    """A Bearer token in hosted cloud mode - the frontend's channel."""

    def test_the_delivery_log_is_readable(self, rest_api, database_name: str) -> None:
        """No level is checked for a token: LOCKED refuses the API-key channel only"""
        response = rest_api.get(EVENTS_URL, environ_overrides=cloud_auth_header(rest_api, USER_ID, database_name))

        assert response.status_code == HTTPStatus.OK


class TestOnPremise:
    """No cloud mode: verify_api_access checks nothing."""

    def test_the_delivery_log_is_readable(self, rest_api, events) -> None:
        """LOCKED means nothing without the cloud API"""
        del events

        assert rest_api.get(EVENTS_URL).status_code == HTTPStatus.OK
