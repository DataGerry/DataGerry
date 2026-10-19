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
Functional tests for where a webhook may deliver to

A webhook's URL whose host resolves to a non-public address is refused with a 400 naming the reason, on create and
on update, and nothing is stored; a public destination - and a host that does not resolve - is accepted as before.
An operator's ``[Webhooks] allowed_hosts`` lets a named host, or a network holding every address a host resolves to,
through on create and update - and nothing else.
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.interface.rest_api.routes.webhook_routes import webhook_destination
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WEBHOOK_URL_DESTINATION_MSG
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/webhooks'
NAME: str = 'destination-check'
STORED_ID: int = 89951

INTERNAL_URLS: list[str] = [
    'http://127.0.0.1:27017/', 'http://localhost/hook', 'http://10.0.0.5/hook', 'http://169.254.169.254/latest',
    'http://[::1]/hook', 'http://2130706433/',
]
ACCEPTED_URLS: list[str] = ['http://8.8.8.8/hook', 'https://example.test/hook']


def _body(url: str) -> dict[str, Any]:
    """A whole webhook"""
    return {'name': NAME, 'url': url, 'event_types': ['CREATE'], 'active': True}


@pytest.fixture(name='webhooks', autouse=True)
def fixture_webhooks(database_manager: MongoDatabaseManager, database_name: str):
    """One stored webhook to update; every webhook of this module removed around each test"""
    collection = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{'name': NAME}, {'public_id': STORED_ID}]})

    _purge()
    collection.insert_one({'public_id': STORED_ID, 'name': 'stored', 'url': 'https://example.test/hook',
                           'event_types': ['CREATE'], 'active': True})
    yield collection
    _purge()


@pytest.mark.parametrize('url', INTERNAL_URLS)
def test_a_create_to_an_internal_destination_is_refused(rest_api, webhooks, url: str) -> None:
    """400 naming the reason; nothing stored"""
    response = rest_api.post(f'{ROUTE_URL}/', json=_body(url))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'].startswith(WEBHOOK_URL_DESTINATION_MSG.split('{', maxsplit=1)[0])
    assert webhooks.find_one({'name': NAME}) is None


@pytest.mark.parametrize('url', INTERNAL_URLS)
def test_an_update_to_an_internal_destination_is_refused(rest_api, webhooks, url: str) -> None:
    """The stored webhook keeps its destination"""
    response = rest_api.put(f'{ROUTE_URL}/{STORED_ID}', json=_body(url))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert webhooks.find_one({'public_id': STORED_ID})['url'] == 'https://example.test/hook'


@pytest.mark.parametrize('url', ACCEPTED_URLS, ids=['public-address', 'unresolvable-host'])
def test_a_public_or_unresolvable_destination_is_accepted(rest_api, webhooks, url: str) -> None:
    """Unchanged: a public address, and a host the delivery will simply fail to reach"""
    response = rest_api.post(f'{ROUTE_URL}/', json=_body(url))

    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
    assert webhooks.find_one({'name': NAME})['url'] == url


def _allowlist(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """The configuration's ``[Webhooks] allowed_hosts`` - served through the real reader path"""
    reader = MagicMock(name='config_reader')
    reader.get_value.side_effect = lambda name, section, default=None: (
        value if (section, name) == ('Webhooks', 'allowed_hosts') else default)
    monkeypatch.setattr(webhook_destination, 'SystemConfigReader', lambda: reader)


@pytest.mark.parametrize('allowed, url', [
    ('127.0.0.0/8', 'http://127.0.0.1:27017/'),
    ('10.0.0.0/8, ::1', 'http://[::1]/hook'),
    ('LocalHost', 'http://localhost/hook'),
], ids=['network', 'address-in-a-list', 'name-any-case'])
def test_an_allowed_internal_destination_is_accepted(rest_api, webhooks, monkeypatch, allowed: str, url: str) -> None:
    """Create and update both judge with the configured list"""
    _allowlist(monkeypatch, allowed)

    created = rest_api.post(f'{ROUTE_URL}/', json=_body(url))
    updated = rest_api.put(f'{ROUTE_URL}/{STORED_ID}', json=_body(url))

    assert created.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
    assert updated.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
    assert webhooks.find_one({'public_id': STORED_ID})['url'] == url


def test_the_allowlist_lets_through_only_what_it_names(rest_api, webhooks, monkeypatch) -> None:
    """A network of 10.0.0.0/8 does not let 127.0.0.1 through"""
    _allowlist(monkeypatch, '10.0.0.0/8')

    response = rest_api.post(f'{ROUTE_URL}/', json=_body('http://127.0.0.1:27017/'))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert webhooks.find_one({'name': NAME}) is None
