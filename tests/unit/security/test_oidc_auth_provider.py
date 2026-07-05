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
Unit tests for OpenIDConnectAuthenticationProvider (no network - requests are mocked)
"""
import time
from unittest.mock import MagicMock

import pytest
from authlib.jose import jwt, JsonWebKey

from cmdb.security.auth.providers.oidc_auth_config import OpenIDConnectAuthenticationProviderConfig
from cmdb.security.auth.providers.oidc_auth_provider import OpenIDConnectAuthenticationProvider

from cmdb.errors.provider import AuthenticationError, OIDCTokenValidationError
# -------------------------------------------------------------------------------------------------------------------- #

ISSUER = 'https://idp.example.com/realms/dg'
CLIENT_ID = 'datagerry'


def _config(**overrides) -> OpenIDConnectAuthenticationProviderConfig:
    values = dict(OpenIDConnectAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
    values.update({
        'issuer': ISSUER,
        'client_id': CLIENT_ID,
        'jwks_uri': 'https://idp.example.com/jwks',
        'authorization_endpoint': 'https://idp.example.com/auth',
        'token_endpoint': 'https://idp.example.com/token',
    })
    values.update(overrides)
    return OpenIDConnectAuthenticationProviderConfig(**values)


def _provider(config=None, users_manager=None) -> OpenIDConnectAuthenticationProvider:
    return OpenIDConnectAuthenticationProvider(config=config or _config(), users_manager=users_manager)


# --------------------------------------------------- RSA / TOKENS --------------------------------------------------- #

@pytest.fixture(scope='module')
def rsa_key():
    return JsonWebKey.generate_key('RSA', 2048, is_private=True)


@pytest.fixture(scope='module')
def key_set(rsa_key):
    return JsonWebKey.import_key_set({'keys': [rsa_key.as_dict(is_private=False)]})


def _make_id_token(rsa_key, **claim_overrides) -> str:
    now = int(time.time())
    payload = {
        'iss': ISSUER,
        'sub': 'subject-123',
        'aud': CLIENT_ID,
        'exp': now + 300,
        'iat': now,
        'nonce': 'the-nonce',
        'preferred_username': 'Alice',
    }
    payload.update(claim_overrides)
    header = {'alg': 'RS256', 'kid': rsa_key.as_dict()['kid']}
    token = jwt.encode(header, payload, rsa_key)
    return token.decode('utf-8') if isinstance(token, bytes) else token


# --------------------------------------------------- NESTED CLAIM --------------------------------------------------- #

class TestNestedClaim:
    def test_simple(self):
        assert OpenIDConnectAuthenticationProvider._get_nested_claim({'a': 1}, 'a') == 1

    def test_dotted(self):
        claims = {'resource_access': {'myclient': {'roles': ['x']}}}
        assert OpenIDConnectAuthenticationProvider._get_nested_claim(
            claims, 'resource_access.myclient.roles') == ['x']

    def test_missing(self):
        assert OpenIDConnectAuthenticationProvider._get_nested_claim({'a': 1}, 'b') is None
        assert OpenIDConnectAuthenticationProvider._get_nested_claim({'a': 1}, 'a.b') is None


# --------------------------------------------------- CLAIMS EXTRACT ------------------------------------------------- #

class TestExtractClaims:
    def test_userinfo_wins_over_id_token(self):
        provider = _provider()
        data = provider._extract_claims(
            {'preferred_username': 'from_id', 'email': 'id@x'},
            {'preferred_username': 'from_userinfo', 'email': 'userinfo@x'})
        assert data['user_name'] == 'from_userinfo'
        assert data['email'] == 'userinfo@x'

    def test_username_lowercased(self):
        provider = _provider()
        data = provider._extract_claims({'preferred_username': 'Alice'}, None)
        assert data['user_name'] == 'alice'

    def test_sub_fallback(self):
        provider = _provider()
        data = provider._extract_claims({'sub': 'abc'}, None)
        assert data['user_name'] == 'abc'

    def test_empty_username_raises(self):
        provider = _provider()
        with pytest.raises(AuthenticationError):
            provider._extract_claims({}, None)

    def test_groups_string_coerced_to_list(self):
        provider = _provider()
        data = provider._extract_claims({'preferred_username': 'a', 'groups': 'admins'}, None)
        assert data['raw_groups'] == ['admins']

    def test_groups_missing_is_empty(self):
        provider = _provider()
        data = provider._extract_claims({'preferred_username': 'a'}, None)
        assert data['raw_groups'] == []


# ---------------------------------------------------- GROUP MAP ----------------------------------------------------- #

class TestMapOidcGroups:
    def test_inactive_returns_default(self):
        provider = _provider(_config(default_group=2, groups_mapping={'active': False, 'mapping': [
            {'oidc_group': 'admins', 'group_id': 1}]}))
        assert provider._map_oidc_groups(['admins']) == 2

    def test_first_match_wins(self):
        provider = _provider(_config(default_group=2, groups_mapping={'active': True, 'mapping': [
            {'oidc_group': 'admins', 'group_id': 1}]}))
        assert provider._map_oidc_groups(['other', 'admins']) == 1

    def test_no_match_returns_default(self):
        provider = _provider(_config(default_group=2, groups_mapping={'active': True, 'mapping': [
            {'oidc_group': 'admins', 'group_id': 1}]}))
        assert provider._map_oidc_groups(['nope']) == 2

    def test_empty_groups_returns_default(self):
        provider = _provider(_config(default_group=2, groups_mapping={'active': True, 'mapping': [
            {'oidc_group': 'admins', 'group_id': 1}]}))
        assert provider._map_oidc_groups([]) == 2


# ------------------------------------------------- ID TOKEN VALIDATION ---------------------------------------------- #

class TestValidateIdToken:
    def test_valid(self, rsa_key, key_set):
        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        claims = provider._validate_id_token(_make_id_token(rsa_key), 'the-nonce')
        assert claims['sub'] == 'subject-123'

    def test_bad_nonce(self, rsa_key, key_set):
        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        with pytest.raises(OIDCTokenValidationError):
            provider._validate_id_token(_make_id_token(rsa_key), 'wrong-nonce')

    def test_bad_issuer(self, rsa_key, key_set):
        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        with pytest.raises(OIDCTokenValidationError):
            provider._validate_id_token(_make_id_token(rsa_key, iss='https://evil'), 'the-nonce')

    def test_wrong_audience(self, rsa_key, key_set):
        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        with pytest.raises(OIDCTokenValidationError):
            provider._validate_id_token(_make_id_token(rsa_key, aud='someone-else'), 'the-nonce')

    def test_expired(self, rsa_key, key_set):
        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        now = int(time.time())
        token = _make_id_token(rsa_key, exp=now - 1000, iat=now - 2000)
        with pytest.raises(OIDCTokenValidationError):
            provider._validate_id_token(token, 'the-nonce')

    def test_bad_signature(self, rsa_key, key_set):
        # Sign with a different key than the one in the key set
        other_key = JsonWebKey.generate_key('RSA', 2048, is_private=True)
        now = int(time.time())
        header = {'alg': 'RS256', 'kid': rsa_key.as_dict()['kid']}
        payload = {'iss': ISSUER, 'sub': 's', 'aud': CLIENT_ID, 'exp': now + 300,
                   'iat': now, 'nonce': 'the-nonce'}
        forged = jwt.encode(header, payload, other_key)
        forged = forged.decode('utf-8') if isinstance(forged, bytes) else forged

        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        with pytest.raises(OIDCTokenValidationError):
            provider._validate_id_token(forged, 'the-nonce')

    def test_multi_audience_requires_azp(self, rsa_key, key_set):
        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        token = _make_id_token(rsa_key, aud=[CLIENT_ID, 'other'])  # no azp
        with pytest.raises(OIDCTokenValidationError):
            provider._validate_id_token(token, 'the-nonce')

    def test_multi_audience_with_correct_azp(self, rsa_key, key_set):
        provider = _provider()
        provider._load_jwks = lambda force=False: key_set
        token = _make_id_token(rsa_key, aud=[CLIENT_ID, 'other'], azp=CLIENT_ID)
        claims = provider._validate_id_token(token, 'the-nonce')
        assert claims['azp'] == CLIENT_ID


# --------------------------------------------------- AUTHENTICATE --------------------------------------------------- #

class TestAuthenticate:
    def test_authenticate_always_raises(self):
        """Auth-bypass regression: OIDC password auth must always fail."""
        provider = _provider()
        with pytest.raises(AuthenticationError):
            provider.authenticate('admin', 'admin')


# ------------------------------------------------- LOGIN OR PROVISION ----------------------------------------------- #

class TestLoginOrProvision:
    def test_jit_creates_new_user(self):
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.insert_user.return_value = 42
        created = MagicMock()
        users_manager.get_user.return_value = created

        provider = _provider(_config(jit_provisioning=True), users_manager=users_manager)
        data = {'user_name': 'newuser', 'email': 'n@x', 'first_name': 'N', 'last_name': 'U'}
        result = provider.login_or_provision(data, 3)

        assert result is created
        inserted = users_manager.insert_user.call_args[0][0]
        assert inserted['user_name'] == 'newuser'
        assert inserted['group_id'] == 3
        assert inserted['active'] is True
        assert inserted['authenticator'] == 'OpenIDConnectAuthenticationProvider'

    def test_jit_disabled_raises(self):
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None

        provider = _provider(_config(jit_provisioning=False), users_manager=users_manager)
        with pytest.raises(AuthenticationError):
            provider.login_or_provision({'user_name': 'ghost'}, 2)
        users_manager.insert_user.assert_not_called()

    def test_existing_user_group_updated_when_mapping_active(self):
        existing = MagicMock()
        existing.authenticator = 'OpenIDConnectAuthenticationProvider'
        existing.group_id = 2
        existing.public_id = 7
        existing.email = 'old@x'
        existing.first_name = 'Old'
        existing.last_name = 'Name'

        users_manager = MagicMock()
        users_manager.get_user_by.return_value = existing

        provider = _provider(_config(groups_mapping={'active': True, 'mapping': []}),
                             users_manager=users_manager)
        provider.login_or_provision({'user_name': 'alice'}, 5)

        assert existing.group_id == 5
        users_manager.update_user.assert_called_once()

    def test_existing_foreign_authenticator_returned_as_is(self):
        existing = MagicMock()
        existing.authenticator = 'LocalAuthenticationProvider'

        users_manager = MagicMock()
        users_manager.get_user_by.return_value = existing

        provider = _provider(users_manager=users_manager)
        result = provider.login_or_provision({'user_name': 'admin'}, 5)

        assert result is existing
        users_manager.update_user.assert_not_called()
