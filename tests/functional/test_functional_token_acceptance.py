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
Functional tests for what a protected route does with a token

The token layer is unit-tested in `tests/unit/security/token/`; what is pinned HERE is the part that
only exists once the decorators are stacked on a real route:

* **an expired token is refused end-to-end.** Expiry is enforced in exactly one place -
  `route_utils.parse_authorization_header` -> `_validate_bearer` - while the per-route decorators
  only decode, and `decode_token` accepts an expired token by design. Nothing but a request through
  the stack proves the two halves are still wired together.
* **a server-side key problem answers 500, not 401.** Until 2026-09-10 every failure inside
  `decode_token` became `TokenValidationError`, so an installation with unusable key material told
  every client its token was invalid - which logs the user out instead of reporting an outage.
* **the token is accepted once per request.** The header parse (which validates) and the decode are
  cached on the request, because a route carries up to three decorators that each used to redo the
  whole chain: one GET was measured at 4 decodes and 12 reads of the RSA key document.

The tokens here are signed with the installation's own key through `KeyHolder`, so the signatures
are real; only the claims are chosen by the test.
"""
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from cmdb.database import MongoDatabaseManager
from cmdb.security.key.holder import KeyHolder
from cmdb.security.token import validator as validator_module
from cmdb.security.token.token_constants import (
    TokenAlgorithm,
    TokenClaim,
    TokenClaimWrapperKey,
    TokenTimeClaim,
)

from cmdb import __title__
# -------------------------------------------------------------------------------------------------------------------- #

PROTECTED_ROUTE: str = '/types/'
ADMIN_USER_ID: int = 1


def _signed_token(
        database_manager: MongoDatabaseManager,
        *,
        lifetime: timedelta = timedelta(hours=1),
        issued_ago: timedelta = timedelta(0),
        issuer: Any = __title__) -> str:
    """Signs a DataGerry token with the installation's real private key."""
    issued_at = datetime.now(timezone.utc) - issued_ago
    claims: dict[str, Any] = {
        TokenClaim.ISSUER.value: {
            TokenClaimWrapperKey.ESSENTIAL.value: True,
            TokenClaimWrapperKey.VALUE.value: issuer,
        },
        TokenTimeClaim.ISSUED_AT.value: int(issued_at.timestamp()),
        TokenTimeClaim.EXPIRATION.value: int((issued_at + lifetime).timestamp()),
        TokenClaim.DATAGERRY.value: {
            TokenClaimWrapperKey.ESSENTIAL.value: True,
            TokenClaimWrapperKey.VALUE.value: {'user': {'public_id': ADMIN_USER_ID}},
        },
    }
    private_key = RSAKey.import_key(KeyHolder(database_manager).rsa_private)

    return jwt.encode({'alg': TokenAlgorithm.RS512.value}, claims, private_key,
                      algorithms=[TokenAlgorithm.RS512.value])


@pytest.fixture(name='bare_client')
def fixture_bare_client(rest_api):
    """
    The test client without its own Authorization header, so the test's header is the only one

    The client is session-scoped and injects a valid token through `environ_base`; that entry is
    removed for the duration of the test and **put back afterwards**, or every later test in the
    session would run unauthenticated.
    """
    injected_header = rest_api.environ_base.pop('HTTP_AUTHORIZATION', None)

    yield rest_api

    if injected_header is not None:
        rest_api.environ_base['HTTP_AUTHORIZATION'] = injected_header


class TestTokenAcceptance:
    """What the stack does with a valid, an expired and a foreign token."""

    def test_a_valid_token_is_accepted(self, bare_client, database_manager: MongoDatabaseManager) -> None:
        """The baseline: a token inside its lifetime reaches the route"""
        token = _signed_token(database_manager)

        response = bare_client.get(PROTECTED_ROUTE, headers={'Authorization': f'Bearer {token}'})

        assert response.status_code == HTTPStatus.OK

    def test_an_expired_token_is_refused(self, bare_client, database_manager: MongoDatabaseManager) -> None:
        """
        The property no unit test can prove: the validating step is still in the request path

        `decode_token` - which the per-route decorators call - accepts this token; only
        `_validate_bearer` refuses it.
        """
        token = _signed_token(database_manager, issued_ago=timedelta(hours=2), lifetime=timedelta(minutes=1))

        response = bare_client.get(PROTECTED_ROUTE, headers={'Authorization': f'Bearer {token}'})

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_a_token_from_another_issuer_is_refused(
            self, bare_client, database_manager: MongoDatabaseManager) -> None:
        """A validly signed token that does not name this product is not accepted"""
        token = _signed_token(database_manager, issuer='SomeOtherProduct')

        response = bare_client.get(PROTECTED_ROUTE, headers={'Authorization': f'Bearer {token}'})

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_a_garbage_token_is_refused(self, bare_client) -> None:
        """Whatever arrives in the header reaches the validator unchecked"""
        response = bare_client.get(PROTECTED_ROUTE, headers={'Authorization': 'Bearer not.a.token'})

        assert response.status_code == HTTPStatus.UNAUTHORIZED


class TestServerSideKeyFailure:
    """A key problem is the server's fault, and the status has to say so."""

    def test_unusable_key_material_answers_500(self, bare_client, database_manager, monkeypatch) -> None:
        """
        Not 401

        A 401 tells the frontend the session is over and logs the user out; the token was fine, the
        installation is not.
        """
        token = _signed_token(database_manager)

        class _BrokenKeyHolder:
            """A holder whose public key cannot be used."""

            def __init__(self, dbm: Any, with_private_key: bool = True) -> None:
                """Ignores its arguments and answers unusable key material."""
                del dbm, with_private_key
                self.rsa_public = b'not a key'
                self.rsa_private = None

        monkeypatch.setattr(validator_module, 'KeyHolder', _BrokenKeyHolder)

        response = bare_client.get(PROTECTED_ROUTE, headers={'Authorization': f'Bearer {token}'})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestTheTokenIsAcceptedOncePerRequest:
    """The per-request cache, measured the way the audit measured the original cost."""

    def test_one_decode_and_one_key_read_per_request(
            self, bare_client, database_manager: MongoDatabaseManager, monkeypatch) -> None:
        """
        One decode, one claim validation, one key read - for a route carrying three decorators

        Before the cache this was 4 decodes and 12 reads of the RSA key document, because every
        decorator re-parsed the header (which validates) and decoded again.
        """
        counters = {'decodes': 0, 'claims': 0, 'public': 0, 'private': 0}
        original_decode = validator_module.TokenValidator.decode_token
        original_claims = validator_module.TokenValidator.validate_claims
        original_public = KeyHolder.get_public_key
        original_private = KeyHolder.get_private_key

        def decode(self, token):
            """Counts signature verifications."""
            counters['decodes'] += 1

            return original_decode(self, token)

        def claims(self, decoded):
            """Counts claim validations."""
            counters['claims'] += 1

            return original_claims(self, decoded)

        def public(self):
            """Counts public-key loads."""
            counters['public'] += 1

            return original_public(self)

        def private(self):
            """Counts private-key loads."""
            counters['private'] += 1

            return original_private(self)

        monkeypatch.setattr(validator_module.TokenValidator, 'decode_token', decode)
        monkeypatch.setattr(validator_module.TokenValidator, 'validate_claims', claims)
        monkeypatch.setattr(KeyHolder, 'get_public_key', public)
        monkeypatch.setattr(KeyHolder, 'get_private_key', private)

        token = _signed_token(database_manager)
        counters.update({'decodes': 0, 'claims': 0, 'public': 0, 'private': 0})

        response = bare_client.get(PROTECTED_ROUTE, headers={'Authorization': f'Bearer {token}'})

        assert response.status_code == HTTPStatus.OK
        assert counters['decodes'] == 1
        assert counters['claims'] == 1
        assert counters['public'] == 1
        assert counters['private'] == 0

    def test_a_second_request_validates_again(
            self, bare_client, database_manager: MongoDatabaseManager, monkeypatch) -> None:
        """
        The cache is per REQUEST, not per token

        A token cached beyond its request would keep working after it expired.
        """
        counters = {'claims': 0}
        original_claims = validator_module.TokenValidator.validate_claims

        def claims(self, decoded):
            """Counts claim validations across both requests."""
            counters['claims'] += 1

            return original_claims(self, decoded)

        monkeypatch.setattr(validator_module.TokenValidator, 'validate_claims', claims)

        token = _signed_token(database_manager)
        headers = {'Authorization': f'Bearer {token}'}

        assert bare_client.get(PROTECTED_ROUTE, headers=headers).status_code == HTTPStatus.OK
        assert bare_client.get(PROTECTED_ROUTE, headers=headers).status_code == HTTPStatus.OK
        assert counters['claims'] == 2
