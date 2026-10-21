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
Functional tests of the setup cache routes, through a cloud-mode app and the real decorator chain

The setup blueprint exists only in cloud mode, so it is mounted on its own cloud-mode app here. The request carries
what the Service Portal sends - HTTP Basic plus an ``x-api-key`` - and the portal's answer is stubbed with a
SUPER_ADMIN account, so ``verify_api_access`` and ``handle_route_errors`` run for real. The cache manager is pointed
at the test database instead of the shared cache database.

Pinned: a teardown naming an address in another spelling evicts the cached entry, and every route still answers the
flat ``true`` the portal parses; a malformed eviction is a 400 that evicts nothing; and only the portal's channel gets
in - a Bearer request (any token) or one without credentials is a 401 that changes nothing
"""
import base64
from http import HTTPStatus
from typing import Any

import pytest
from flask import Flask

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.models.cached_user_model import CmdbCachedUser
from cmdb.interface import route_utils
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.setup_routes import setup_routes
from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

CACHE_USER_ROUTE: str = '/setup/cache/user'
CACHE_USER_ALL_ROUTE: str = '/setup/cache/user/all'
CACHED_EMAILS: list[str] = ['itest-setup-a@acme.com', 'itest-setup-b@acme.com']

PORTAL_CREDENTIALS: str = base64.b64encode(b'portal@datagerry.com:portal-password').decode('ascii')
PORTAL_HEADERS: dict[str, str] = {'Authorization': f'Basic {PORTAL_CREDENTIALS}', 'x-api-key': 'portal-key'}


@pytest.fixture(name='cache')
def fixture_cache(database_manager: MongoDatabaseManager, database_name: str):
    """The cache collection of the test database, seeded with two entries and emptied of them afterwards"""
    collection = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)
    collection.delete_many({'email': {'$in': CACHED_EMAILS}})
    collection.insert_many([{'email': email, 'password': 'hashed'} for email in CACHED_EMAILS])

    yield collection

    collection.delete_many({'email': {'$in': CACHED_EMAILS}})


@pytest.fixture(name='portal_client')
def fixture_portal_client(monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                          database_name: str):
    """A cloud-mode app carrying only the setup blueprint, reached the way the Service Portal reaches it"""
    app = Flask(__name__)
    app.cloud_mode = True
    app.local_mode = False
    app.database_manager = database_manager
    app.register_blueprint(setup_blueprint, url_prefix='/setup')

    portal_account: dict[str, Any] = {'api_level': ApiLevel.SUPER_ADMIN.value, 'subscriptions': []}
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal_account)

    def _test_cache_manager() -> CachedUserManager:
        manager = CachedUserManager(database_manager)
        manager.db_name = database_name
        return manager

    monkeypatch.setattr(setup_routes, 'get_cached_user_manager', _test_cache_manager)

    return app.test_client()


def _remaining(cache) -> list[str]:
    """The seeded addresses still cached"""
    return sorted(document['email'] for document in cache.find({'email': {'$in': CACHED_EMAILS}}))


def test_another_spelling_evicts_the_cached_entry(portal_client, cache) -> None:
    """'  ITest-Setup-A@Acme.com ' names the stored lower-case entry - it used to stay cached behind a 'true'"""
    response = portal_client.delete(CACHE_USER_ROUTE, headers=PORTAL_HEADERS,
                                    json={'email': '  ITest-Setup-A@Acme.com '})

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() is True
    assert _remaining(cache) == [CACHED_EMAILS[1]]


def test_a_list_evicts_every_named_entry(portal_client, cache) -> None:
    """Both addresses, in other spellings, in one request"""
    response = portal_client.delete(CACHE_USER_ROUTE, headers=PORTAL_HEADERS,
                                    json={'email': [email.upper() for email in CACHED_EMAILS]})

    assert response.get_json() is True
    assert not _remaining(cache)


def test_an_uncached_address_is_still_answered_true(portal_client, cache) -> None:
    """The flat answer is the contract; the log says nothing was evicted"""
    response = portal_client.delete(CACHE_USER_ROUTE, headers=PORTAL_HEADERS, json={'email': 'nobody@acme.com'})

    assert response.get_json() is True
    assert _remaining(cache) == CACHED_EMAILS


@pytest.mark.parametrize('email', [[], [CACHED_EMAILS[0], None], ''], ids=['empty-list', 'null-entry', 'empty'])
def test_a_malformed_eviction_is_a_400_and_evicts_nothing(portal_client, cache, email: Any) -> None:
    """Even the usable address in a malformed list stays cached"""
    response = portal_client.delete(CACHE_USER_ROUTE, headers=PORTAL_HEADERS, json={'email': email})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _remaining(cache) == CACHED_EMAILS


def test_clearing_the_cache_answers_true(portal_client, cache) -> None:
    """Every entry is gone; the count went to the log"""
    response = portal_client.delete(CACHE_USER_ALL_ROUTE, headers=PORTAL_HEADERS)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() is True
    assert cache.count_documents({}) == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                         ONLY THE PORTAL'S CHANNEL GETS IN                                            #
# -------------------------------------------------------------------------------------------------------------------- #
BEARER_HEADERS: dict[str, str] = {'Authorization': 'Bearer not-a-real-token', 'x-api-key': 'portal-key'}


@pytest.mark.parametrize(('route', 'body'), [
    (CACHE_USER_ROUTE, {'email': CACHED_EMAILS[0]}),
    (CACHE_USER_ALL_ROUTE, None),
], ids=['evict', 'clear'])
def test_a_bearer_request_is_refused_and_changes_nothing(portal_client, cache, route: str, body: Any) -> None:
    """verify_api_access let this through and nothing checked the token - the cache was evicted by anyone"""
    response = portal_client.delete(route, headers=BEARER_HEADERS, json=body)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert _remaining(cache) == CACHED_EMAILS


def test_a_request_without_credentials_is_refused(portal_client, cache) -> None:
    """No header at all is refused by the same guard"""
    response = portal_client.delete(CACHE_USER_ALL_ROUTE)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert _remaining(cache) == CACHED_EMAILS


@pytest.mark.parametrize('route', [CACHE_USER_ROUTE, CACHE_USER_ALL_ROUTE], ids=['evict', 'clear'])
def test_the_slash_form_is_a_404_and_changes_nothing(portal_client, cache, route: str) -> None:
    """The portal's spelling has no trailing slash; the slash form is not the same route"""
    response = portal_client.delete(f'{route}/', headers=PORTAL_HEADERS, json={'email': CACHED_EMAILS[0]})

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _remaining(cache) == CACHED_EMAILS

