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
Functional coverage for a request whose token key cannot be READ - the server's fault, never the caller's

The key is read when the validator (or, for HTTP Basic, the generator) is built, before any token is looked at.
Whatever goes wrong there used to reach the route's catch-all and answer 401, which the frontend takes as "the
session is over" and logs the user out. Now:

  - a key that is missing or unusable - no stored keypair, a keypair without its public half, an unreadable
    settings document, an unset or malformed ``DG_RSA_PUBLIC_KEY`` - answers **500** with the key-problem message
  - the database server lost while the key is read answers **503** (try again)
  - Basic credentials the server cannot sign for answer 500 too, not a failed login
  - the key is read, and the fault logged at ERROR, once per request

And on premise a keypair that WAS read is read once per process, not once per request - while a failed read is
not kept, so the request after the key is repaired succeeds without a restart
"""
import base64
import logging
from http import HTTPStatus
from typing import Any, Callable

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from cmdb.errors.database import DocumentGetError
from cmdb.interface.rest_api.responses.error_handlers import DATABASE_UNAVAILABLE_MSG
from cmdb.interface.route_utils import KEY_MATERIAL_UNAVAILABLE_MESSAGE
from cmdb.security.key import holder as holder_module
from cmdb.security.key.holder import PUBLIC_KEY_ENV_VAR
from cmdb.security.key.security_settings import read_security_setting

from tests.utils.cloud_mode import enable_hosted_cloud_mode
from tests.utils.flask_test_client import without_injected_auth
# -------------------------------------------------------------------------------------------------------------------- #

PROTECTED_ROUTE: str = '/types/'
ADMIN_USER_ID: int = 1
ADMIN_CREDENTIALS: bytes = b'admin:admin'
NOT_BASE64: str = '%%% not base64 %%%'
REQUEST_COUNT: int = 5


def _no_keypair(*_: Any) -> Any:
    """No security document holding the keypair"""
    return None


def _no_public_half(*_: Any) -> Any:
    """A keypair without its public half"""
    return {'private': b'private'}


def _unreadable(*_: Any) -> Any:
    """A settings read that failed - not an outage"""
    raise DocumentGetError('unreadable settings document')


def _server_lost(*_: Any) -> Any:
    """The read as an outage reports it: the manager's error over the driver's"""
    try:
        raise ServerSelectionTimeoutError('no server')
    except ServerSelectionTimeoutError as err:
        raise DocumentGetError(err) from err


@pytest.fixture(name='bare_client')
def fixture_bare_client(rest_api):
    """The test client without its own Authorization header, so the test's header is the only one"""
    with without_injected_auth(rest_api) as client:
        yield client


@pytest.fixture(name='bearer')
def fixture_bearer(rest_api) -> dict[str, str]:
    """A valid Bearer header, signed before the test breaks the key"""
    token: str = rest_api._token_generator.generate_token(  # pylint: disable=protected-access
        payload={'user': {'public_id': ADMIN_USER_ID}}
    ).decode('UTF-8')

    return {'Authorization': f'Bearer {token}'}


def _key_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The ERROR records the key load wrote"""
    return [record for record in caplog.records
            if record.name == holder_module.LOGGER.name and record.levelno >= logging.ERROR]


class TestOnPremise:
    """The keypair lives in the security settings document"""

    @pytest.mark.parametrize('read', [_no_keypair, _no_public_half, _unreadable],
                             ids=['no-keypair', 'no-public-half', 'unreadable'])
    def test_a_key_that_cannot_be_read_answers_500(
            self, bare_client, bearer: dict[str, str], monkeypatch: pytest.MonkeyPatch,
            caplog: pytest.LogCaptureFixture, read: Callable[..., Any]) -> None:
        """Not 401: the token is fine, the installation is not - read and logged once"""
        monkeypatch.setattr(holder_module, 'read_security_setting', read)
        caplog.set_level(logging.ERROR, logger=holder_module.LOGGER.name)

        response = bare_client.get(PROTECTED_ROUTE, headers=bearer)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == KEY_MATERIAL_UNAVAILABLE_MESSAGE
        assert len(_key_errors(caplog)) == 1

    def test_a_lost_database_answers_503(
            self, bare_client, bearer: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        """An outage while the key is read is "try again", not a broken installation and not a bad token"""
        monkeypatch.setattr(holder_module, 'read_security_setting', _server_lost)

        response = bare_client.get(PROTECTED_ROUTE, headers=bearer)

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.get_json()['message'] == DATABASE_UNAVAILABLE_MSG

    def test_basic_credentials_the_server_cannot_sign_for_answer_500(
            self, bare_client, monkeypatch: pytest.MonkeyPatch) -> None:
        """The login itself succeeds; signing its token fails - the server's fault, not a failed login"""
        monkeypatch.setattr(holder_module, 'read_security_setting', _no_keypair)
        basic = {'Authorization': f"Basic {base64.b64encode(ADMIN_CREDENTIALS).decode('ascii')}"}

        response = bare_client.get(PROTECTED_ROUTE, headers=basic)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == KEY_MATERIAL_UNAVAILABLE_MESSAGE

    def test_wrong_basic_credentials_are_still_401(self, bare_client) -> None:
        """The key is fine: a failed login keeps its own answer"""
        basic = {'Authorization': f"Basic {base64.b64encode(b'admin:wrong').decode('ascii')}"}

        assert bare_client.get(PROTECTED_ROUTE, headers=basic).status_code == HTTPStatus.UNAUTHORIZED


class TestHostedCloud:
    """The public key comes from DG_RSA_PUBLIC_KEY"""

    @pytest.mark.parametrize('value', [None, NOT_BASE64], ids=['unset', 'not-base64'])
    def test_a_variable_that_cannot_be_read_answers_500(
            self, bare_client, rest_api, database_manager, bearer: dict[str, str],
            monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, value: str | None) -> None:
        """The same server-side fault in the other mode - and the key is read once, not twice, per request"""
        enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)

        if value is None:
            monkeypatch.delenv(PUBLIC_KEY_ENV_VAR)
        else:
            monkeypatch.setenv(PUBLIC_KEY_ENV_VAR, value)

        caplog.set_level(logging.ERROR, logger=holder_module.LOGGER.name)

        response = bare_client.get(PROTECTED_ROUTE, headers=bearer)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == KEY_MATERIAL_UNAVAILABLE_MESSAGE
        assert len(_key_errors(caplog)) == 1


class _CountingRead:
    """The real settings read, counted - optionally answering 'nothing stored' for the first few calls"""

    def __init__(self, failing_first: int = 0) -> None:
        self.reads: int = 0
        self.failing_first: int = failing_first

    def __call__(self, dbm: Any, database: str | None, key: str) -> Any:
        """Counts the read; answers None while it is still failing, the stored value afterwards"""
        self.reads += 1

        if self.reads <= self.failing_first:
            return None

        return read_security_setting(dbm, database, key)


class TestTheKeypairIsReadOncePerProcess:
    """One Mongo read for the keypair per process, not one per authenticated request"""

    def test_many_requests_read_the_keypair_once(
            self, bare_client, bearer: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        """Every request builds its own validator - none reads the keypair after the first"""
        read = _CountingRead()
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        statuses = [bare_client.get(PROTECTED_ROUTE, headers=bearer).status_code for _ in range(REQUEST_COUNT)]

        assert statuses == [HTTPStatus.OK] * REQUEST_COUNT
        assert read.reads == 1

    def test_a_failed_read_is_not_kept(
            self, bare_client, bearer: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The keypair missing on the first request, present on the next: 500, then 200 - no restart needed

        Had the failure been kept, every request after it would answer 500 until the process restarted
        """
        read = _CountingRead(failing_first=1)
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        statuses = [bare_client.get(PROTECTED_ROUTE, headers=bearer).status_code for _ in range(REQUEST_COUNT)]

        assert statuses == [HTTPStatus.INTERNAL_SERVER_ERROR] + [HTTPStatus.OK] * (REQUEST_COUNT - 1)
        assert read.reads == 2
