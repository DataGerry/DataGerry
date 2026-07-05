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
Implementation of OpenIDConnectAuthenticationProviderConfig
"""
from logging import Logger, getLogger

from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig

from cmdb.errors.provider import GroupMappingError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                    OpenIDConnectAuthenticationProviderConfig - CLASS                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class OpenIDConnectAuthenticationProviderConfig(BaseAuthProviderConfig):
    """
    Configuration class for the OpenID Connect Authentication Provider.

    This class is pure data and performs no I/O. It is re-parsed by AuthModule on every
    login, so it must stay side-effect free.

    Extends: BaseAuthProviderConfig
    """
    DEFAULT_CLAIMS_MAPPING = {
        'user_name': 'preferred_username',
        'email': 'email',
        'first_name': 'given_name',
        'last_name': 'family_name',
        'groups': 'groups',
    }

    DEFAULT_CONFIG_VALUES = {
        'active': False,
        'jit_provisioning': True,
        'default_group': 2,
        'auto_redirect': False,

        'discovery_url': '',
        'issuer': '',
        'authorization_endpoint': '',
        'token_endpoint': '',
        'userinfo_endpoint': '',
        'jwks_uri': '',

        'client_id': '',
        'client_secret': '',
        'token_endpoint_auth_method': 'client_secret_basic',
        'scopes': ['openid', 'profile', 'email'],

        'redirect_uri': '',
        'frontend_origins': [],

        'claims_mapping': dict(DEFAULT_CLAIMS_MAPPING),
        'groups_mapping': {'active': False, 'mapping': []},
    }

    def __init__(
        self,
        active: bool = None,
        jit_provisioning: bool = None,
        default_group: int = None,
        auto_redirect: bool = None,
        discovery_url: str = None,
        issuer: str = None,
        authorization_endpoint: str = None,
        token_endpoint: str = None,
        userinfo_endpoint: str = None,
        jwks_uri: str = None,
        client_id: str = None,
        client_secret: str = None,
        token_endpoint_auth_method: str = None,
        scopes=None,
        redirect_uri: str = None,
        frontend_origins=None,
        claims_mapping: dict = None,
        groups_mapping: dict = None,
        *args, **kwargs):
        """
        Initialize an OpenID Connect Authentication Provider Configuration instance

        Every schema key is an explicit keyword argument, with **kwargs tolerance so that
        obsolete/extra persisted keys do not break parsing.
        """
        defaults = OpenIDConnectAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES

        self.jit_provisioning: bool = jit_provisioning if jit_provisioning is not None else defaults['jit_provisioning']
        self.default_group: int = self._to_int(default_group, defaults['default_group'])
        self.auto_redirect: bool = auto_redirect if auto_redirect is not None else defaults['auto_redirect']

        self.discovery_url: str = (discovery_url or '').strip()
        self.issuer: str = (issuer or '').strip()
        self.authorization_endpoint: str = (authorization_endpoint or '').strip()
        self.token_endpoint: str = (token_endpoint or '').strip()
        self.userinfo_endpoint: str = (userinfo_endpoint or '').strip()
        self.jwks_uri: str = (jwks_uri or '').strip()

        self.client_id: str = (client_id or '').strip()
        self.client_secret: str = client_secret or ''
        self.token_endpoint_auth_method: str = token_endpoint_auth_method or defaults['token_endpoint_auth_method']

        self.scopes: list = self._normalize_scopes(scopes)
        self.redirect_uri: str = (redirect_uri or '').strip()
        self.frontend_origins: list = self._normalize_origins(frontend_origins)

        self.claims_mapping: dict = self._merge_claims_mapping(claims_mapping)
        self.groups_mapping: dict = groups_mapping or {'active': False, 'mapping': []}

        super().__init__(active if active is not None else False)


    @staticmethod
    def _to_int(value, fallback: int) -> int:
        """
        Coerce a value to int, falling back to the given default on failure
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(fallback)


    @staticmethod
    def _normalize_scopes(scopes) -> list:
        """
        Normalize scopes to a list of strings and guarantee that 'openid' is present

        Accepts a list or a comma/space-separated string
        """
        if not scopes:
            result = ['openid', 'profile', 'email']
        elif isinstance(scopes, str):
            result = [scope for scope in scopes.replace(',', ' ').split() if scope]
        else:
            result = [str(scope).strip() for scope in scopes if str(scope).strip()]

        if 'openid' not in result:
            result.insert(0, 'openid')

        return result


    @staticmethod
    def _normalize_origins(frontend_origins) -> list:
        """
        Normalize frontend origins to a list of strings

        Accepts a list or a comma/space-separated string
        """
        if not frontend_origins:
            return []

        if isinstance(frontend_origins, str):
            return [origin.strip() for origin in frontend_origins.replace(',', ' ').split() if origin.strip()]

        return [str(origin).strip() for origin in frontend_origins if str(origin).strip()]


    @staticmethod
    def _merge_claims_mapping(claims_mapping: dict) -> dict:
        """
        Merge the provided claims mapping over the defaults so partial saves keep all 5 keys
        """
        merged = dict(OpenIDConnectAuthenticationProviderConfig.DEFAULT_CLAIMS_MAPPING)

        if isinstance(claims_mapping, dict):
            for key, value in claims_mapping.items():
                if key in merged and value:
                    merged[key] = value

        return merged


    def mapping(self, oidc_group: str) -> int:
        """
        Get the internal group ID mapped to a specific OIDC group/role value

        Args:
            oidc_group (str): The OIDC group/role claim value

        Raises:
            GroupMappingError: If no mapping is found for the given value

        Returns:
            int: The corresponding internal group ID
        """
        try:
            return next(int(group['group_id']) for group in self.groups_mapping['mapping'] if
                        str(group['oidc_group']).lower() == str(oidc_group).lower())
        except StopIteration as err:
            raise GroupMappingError(err) from err
