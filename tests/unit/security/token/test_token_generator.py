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
Unit tests for cmdb.security.token.generator

The signer of every login token. Real RSA keys are generated per test and decoded back with the public
half, so the claims asserted here are the ones actually signed. KeyHolder and SettingsManager are stubbed
- nothing touches a database or a Flask app.

What is pinned:

* **a database manager is required** - the key and the settings are both read through it, so a default
  of None only moved the failure later
* **the token lifetime is read from the database the token is for** - the tenant's in cloud mode (a
  generator that read the default database ignored every tenant's own `token_lifetime`)
* **one expiry**: `generate_token_with_times` answers the `iat` / `exp` it signed, so the login
  response's `token_expire` is the token's own `exp`
* **the lifetime is read without an AuthModule**: a missing section or key is the default, a malformed
  section fails exactly as the login would
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from cmdb.models.security_models.auth_settings_constants import (
    AUTH_SETTINGS_ID,
    DEFAULT_TOKEN_LIFETIME,
    AuthSettingsKey,
)
from cmdb.security.token import generator as generator_module
from cmdb.security.token.generator import TokenGenerator, read_token_lifetime
from cmdb.security.token.token_constants import TokenAlgorithm, TokenClaim, TokenClaimWrapperKey, TokenTimeClaim

from cmdb.errors.models.cmdb_auth_settings.cmdb_auth_settings_errors import AuthSettingsInitError
# -------------------------------------------------------------------------------------------------------------------- #

SECONDS_PER_MINUTE: int = 60
CONFIGURED_LIFETIME: int = 30
TENANT_DATABASE: str = 'tenant-db'
PAYLOAD: dict[str, Any] = {'user': {'public_id': 1}}


class _StubSettingsManager:
    """Stands in for SettingsManager: answers one stored section and records the database it was bound to"""

    bound_to: list[str | None] = []
    section: dict[str, Any] | None = None

    def __init__(self, dbm: Any, database: str | None = None) -> None:
        """Records the database the generator asked for"""
        del dbm
        _StubSettingsManager.bound_to.append(database)

    def get_section(self, section_name: str) -> dict[str, Any] | None:
        """The stored section, when the auth section is asked for"""
        return _StubSettingsManager.section if section_name == AUTH_SETTINGS_ID else None


@pytest.fixture(name='key')
def fixture_key() -> RSAKey:
    """A freshly generated RSA key pair"""
    return RSAKey.generate_key(2048)


@pytest.fixture(autouse=True)
def _stubs(monkeypatch: pytest.MonkeyPatch, key: RSAKey) -> None:
    """Replaces the key holder and the settings manager; stores a configured lifetime by default"""
    class _StubKeyHolder:
        """Hands out the generated private key"""

        def __init__(self, dbm: Any) -> None:
            del dbm

        def get_private_key(self) -> bytes:
            """The private half, as PEM"""
            return key.as_pem(private=True)

    _StubSettingsManager.bound_to = []
    _StubSettingsManager.section = {AuthSettingsKey.TOKEN_LIFETIME.value: CONFIGURED_LIFETIME}
    monkeypatch.setattr(generator_module, 'KeyHolder', _StubKeyHolder)
    monkeypatch.setattr(generator_module, 'SettingsManager', _StubSettingsManager)


def _claims(token: bytes, key: RSAKey) -> dict[str, Any]:
    """Decodes a signed token with the public half and answers its claims"""
    return jwt.decode(token.decode('utf-8'), key, algorithms=[TokenAlgorithm.RS512.value]).claims


class TestConstruction:
    """What the generator reads, and from where"""

    def test_a_database_manager_is_required(self) -> None:
        """Left out, the call itself fails - not a key load later"""
        with pytest.raises(TypeError):
            TokenGenerator()  # pylint: disable=no-value-for-parameter

    def test_the_lifetime_is_read_from_the_given_database(self) -> None:
        """The tenant's own auth settings decide, in cloud mode"""
        generator = TokenGenerator(object(), TENANT_DATABASE)

        assert _StubSettingsManager.bound_to == [TENANT_DATABASE]
        assert generator.token_lifetime == CONFIGURED_LIFETIME

    def test_without_a_database_the_managers_own_is_read(self) -> None:
        """On premise there is one database"""
        TokenGenerator(object())

        assert _StubSettingsManager.bound_to == [None]


class TestClaims:
    """The token carries what the validator and the frontend read"""

    def test_the_times_answered_are_the_times_signed(self, key: RSAKey) -> None:
        """The login response reports the token's own iat / exp"""
        token, issued, expires = TokenGenerator(object()).generate_token_with_times(PAYLOAD)
        claims: dict[str, Any] = _claims(token, key)

        assert claims[TokenTimeClaim.ISSUED_AT.value] == issued
        assert claims[TokenTimeClaim.EXPIRATION.value] == expires

    def test_the_expiry_is_the_configured_lifetime_after_the_issue(self) -> None:
        """exp - iat is the auth section's token_lifetime"""
        _, issued, expires = TokenGenerator(object()).generate_token_with_times(PAYLOAD)

        assert expires - issued == CONFIGURED_LIFETIME * SECONDS_PER_MINUTE

    def test_the_payload_and_the_issuer_are_wrapped(self, key: RSAKey) -> None:
        """The shape every consumer reads the acting user out of (the wrapper itself is T218)"""
        claims: dict[str, Any] = _claims(TokenGenerator(object()).generate_token(PAYLOAD), key)

        assert claims[TokenClaim.DATAGERRY.value][TokenClaimWrapperKey.VALUE.value] == PAYLOAD
        assert TokenClaimWrapperKey.VALUE.value in claims[TokenClaim.ISSUER.value]

    def test_an_optional_claim_is_added(self, key: RSAKey) -> None:
        """Optional claims join the defaults"""
        claims: dict[str, Any] = _claims(
            TokenGenerator(object()).generate_token(PAYLOAD, optional_claims={'extra': 'yes'}), key
        )

        assert claims['extra'] == 'yes'

    def test_generate_token_answers_the_token_alone(self) -> None:
        """The bytes route_utils hands back as the Basic-auth token"""
        assert isinstance(TokenGenerator(object()).generate_token(PAYLOAD), bytes)

    def test_get_expire_time_counts_from_the_given_issue_time(self) -> None:
        """A given issue time is the base, not now"""
        issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        expires: datetime = TokenGenerator(object()).get_expire_time(issued_at)

        assert (expires - issued_at).total_seconds() == CONFIGURED_LIFETIME * SECONDS_PER_MINUTE


class TestReadTokenLifetime:
    """The lifetime is read from the auth section alone"""

    @pytest.mark.parametrize('section', [None, {}, {AuthSettingsKey.ID.value: AUTH_SETTINGS_ID}],
                             ids=['no-section', 'empty-section', 'section-without-lifetime'])
    def test_a_missing_lifetime_is_the_default(self, section: dict[str, Any] | None) -> None:
        """What the login itself would read for the same section"""
        _StubSettingsManager.section = section

        assert read_token_lifetime(_StubSettingsManager(object())) == DEFAULT_TOKEN_LIFETIME

    def test_a_malformed_section_fails_as_the_login_would(self) -> None:
        """An unknown key is refused by CmdbAuthSettings, here as on the login path"""
        _StubSettingsManager.section = {'not_an_auth_key': 1}

        with pytest.raises(AuthSettingsInitError):
            read_token_lifetime(_StubSettingsManager(object()))
