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
Functional tests for the ACL rights guarding the /webhooks and /webhook_events routes

Every route is driven twice with `user_has_right` patched at the api_blueprint module path (the one
place `.protect` consults): once granting, to record WHICH right the route asks for, and once denying,
to prove the route answers 403 instead of running. Together these pin the right-per-route table - a
route silently losing its `.protect` would fail the first half, a right being widened the second

The default test user holds every right, so an unpatched suite can never notice a missing guard
"""
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import urlencode

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WebhookRight
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
# -------------------------------------------------------------------------------------------------------------------- #

API_BLUEPRINT_PATH: str = 'cmdb.interface.blueprints.api_blueprint.user_has_right'
WEBHOOKS_URL: str = '/webhooks'
WEBHOOK_EVENTS_URL: str = '/webhook_events'
WEBHOOK_ID: int = 97851
CREATE_NAME: str = 'Rights Hook'

CREATE_QUERY: str = urlencode({
    'name': CREATE_NAME,
    'url': 'http://example.test/hook',
    'event_types': "['CREATE']",
    'active': 'true',
})

# (label, HTTP method, URL, the right the route must ask for)
GUARDED_ROUTES: list[tuple[str, str, str, str]] = [
    ('create_webhook', 'POST', f'{WEBHOOKS_URL}/?{CREATE_QUERY}', WebhookRight.ADD.value),
    ('get_webhook', 'GET', f'{WEBHOOKS_URL}/{WEBHOOK_ID}', WebhookRight.VIEW.value),
    ('get_webhooks', 'GET', f'{WEBHOOKS_URL}/', WebhookRight.VIEW.value),
    ('update_webhook', 'PUT', f'{WEBHOOKS_URL}/{WEBHOOK_ID}?{CREATE_QUERY}', WebhookRight.EDIT.value),
    ('delete_webhook', 'DELETE', f'{WEBHOOKS_URL}/{WEBHOOK_ID}/', WebhookRight.DELETE.value),
    ('get_webhook_event', 'GET', f'{WEBHOOK_EVENTS_URL}/{WEBHOOK_ID}', WebhookRight.VIEW.value),
    ('get_webhook_events', 'GET', f'{WEBHOOK_EVENTS_URL}/', WebhookRight.VIEW.value),
    ('delete_webhook_event', 'DELETE', f'{WEBHOOK_EVENTS_URL}/{WEBHOOK_ID}/', WebhookRight.DELETE.value),
]

ROUTE_IDS: list[str] = [route[0] for route in GUARDED_ROUTES]


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the webhook the granting run of the create route really writes."""
    def _purge() -> None:
        database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
                        .delete_many({'name': CREATE_NAME})

    _purge()
    yield
    _purge()


def _call(rest_api, method: str, url: str):
    """Issues the request with the verb the route is registered for."""
    verb: Callable[..., Any] = getattr(rest_api, method.lower())

    return verb(url)


@pytest.mark.parametrize('label, method, url, expected_right', GUARDED_ROUTES, ids=ROUTE_IDS)
def test_route_requires_its_webhook_right(rest_api, monkeypatch, label, method, url, expected_right) -> None:
    """Each route asks `.protect` for exactly the right of its operation."""
    del label
    asked_rights: list[str] = []

    def _record(right: str, user: Any = None) -> bool:
        del user
        asked_rights.append(right)

        return True

    monkeypatch.setattr(API_BLUEPRINT_PATH, _record)

    _call(rest_api, method, url)

    assert asked_rights == [expected_right]


@pytest.mark.parametrize('label, method, url, expected_right', GUARDED_ROUTES, ids=ROUTE_IDS)
def test_route_without_the_right_is_forbidden(rest_api, monkeypatch, label, method, url, expected_right) -> None:
    """A user lacking the right gets 403 and the handler never runs."""
    del label, expected_right

    monkeypatch.setattr(API_BLUEPRINT_PATH, lambda right, user=None: False)

    assert _call(rest_api, method, url).status_code == HTTPStatus.FORBIDDEN
