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
Unit tests for OpenIDConnectAuthenticationProviderConfig
"""
import pytest

from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.providers.oidc_auth_config import OpenIDConnectAuthenticationProviderConfig

from cmdb.errors.provider import GroupMappingError
# -------------------------------------------------------------------------------------------------------------------- #

OIDC_CLASS = 'OpenIDConnectAuthenticationProvider'


def _config(**overrides) -> OpenIDConnectAuthenticationProviderConfig:
    values = dict(OpenIDConnectAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
    values.update(overrides)
    return OpenIDConnectAuthenticationProviderConfig(**values)


class TestOidcAuthConfigDefaults:
    """Defaults and basic normalization"""

    def test_defaults(self):
        config = _config()
        assert config.active is False
        assert config.jit_provisioning is True
        assert config.default_group == 2
        assert config.auto_redirect is False
        assert config.token_endpoint_auth_method == 'client_secret_basic'
        assert config.scopes == ['openid', 'profile', 'email']
        assert config.claims_mapping == OpenIDConnectAuthenticationProviderConfig.DEFAULT_CLAIMS_MAPPING
        assert config.groups_mapping == {'active': False, 'mapping': []}

    def test_default_group_invalid_falls_back(self):
        assert _config(default_group='not-an-int').default_group == 2
        assert _config(default_group='5').default_group == 5

    def test_tolerates_unknown_keys(self):
        config = OpenIDConnectAuthenticationProviderConfig(active=True, some_removed_key='x')
        assert config.active is True


class TestScopesNormalization:
    """scopes accept list/string and always contain openid"""

    def test_string_scopes_split(self):
        assert _config(scopes='email profile').scopes == ['openid', 'email', 'profile']

    def test_comma_separated_scopes(self):
        assert _config(scopes='openid, profile ,email').scopes == ['openid', 'profile', 'email']

    def test_list_missing_openid_is_injected(self):
        assert _config(scopes=['profile']).scopes == ['openid', 'profile']

    def test_empty_scopes_defaults(self):
        assert _config(scopes=[]).scopes == ['openid', 'profile', 'email']


class TestFrontendOrigins:
    """frontend_origins accept list/string"""

    def test_string_origins(self):
        assert _config(frontend_origins='http://localhost:4200, http://a').frontend_origins == [
            'http://localhost:4200', 'http://a']

    def test_empty(self):
        assert _config(frontend_origins=None).frontend_origins == []


class TestClaimsMappingMerge:
    """claims_mapping is merged over defaults so partial saves keep all 5 keys"""

    def test_partial_claims_merge(self):
        config = _config(claims_mapping={'user_name': 'upn'})
        assert config.claims_mapping['user_name'] == 'upn'
        assert config.claims_mapping['email'] == 'email'
        assert config.claims_mapping['first_name'] == 'given_name'
        assert config.claims_mapping['last_name'] == 'family_name'
        assert config.claims_mapping['groups'] == 'groups'

    def test_empty_claim_value_ignored(self):
        config = _config(claims_mapping={'email': ''})
        assert config.claims_mapping['email'] == 'email'


class TestGroupMapping:
    """mapping() resolves case-insensitively and raises on miss"""

    def test_mapping_hit(self):
        config = _config(groups_mapping={'active': True, 'mapping': [
            {'oidc_group': 'DG-Admins', 'group_id': 1}]})
        assert config.mapping('dg-admins') == 1

    def test_mapping_miss_raises(self):
        config = _config(groups_mapping={'active': True, 'mapping': [
            {'oidc_group': 'other', 'group_id': 3}]})
        with pytest.raises(GroupMappingError):
            config.mapping('unknown')


class TestUpgradeMergeRegression:
    """
    Regression for the auth_module line-92 fix: an existing install that persisted only
    Local + LDAP must still resolve the OIDC provider config (properly wrapped).
    """

    def test_legacy_settings_get_oidc_entry(self):
        legacy = {
            '_id': 'auth',
            'enable_external': True,
            'token_lifetime': 1400,
            'providers': [
                {'class_name': 'LocalAuthenticationProvider', 'config': {'active': True}},
                {'class_name': 'LdapAuthenticationProvider', 'config': {'active': False}},
            ],
        }

        auth_module = AuthModule(legacy)
        oidc_config = auth_module.settings.get_provider_settings(OIDC_CLASS)

        assert oidc_config['active'] is False
        assert 'claims_mapping' in oidc_config
        assert oidc_config['scopes'] == ['openid', 'profile', 'email']
