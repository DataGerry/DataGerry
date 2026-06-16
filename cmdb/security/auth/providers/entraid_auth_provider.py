# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of EntraIdAuthenticationProvider
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
import requests
from authlib.jose import jwt, JsonWebKey
from authlib.jose.errors import BadSignatureError, InvalidClaimError

from cmdb.manager import (
    UsersManager,
    SecurityManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.providers.entraid_auth_config import EntraIdAuthenticationProviderConfig

from cmdb.errors.provider import GroupMappingError, AuthenticationError
from cmdb.errors.manager import BaseManagerUpdateError
from cmdb.errors.manager.users_manager import UsersManagerGetError, UsersManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          EntraIdAuthenticationProvider - CLASS                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class EntraIdAuthenticationProvider(BaseAuthenticationProvider):
    """
    Entra ID (Azure AD) authentication provider that integrates with Microsoft Entra ID
    to authenticate users via OAuth2/OIDC and manage their user group mappings.

    Extends: BaseAuthenticationProvider

    Attributes:
        PASSWORD_ABLE (bool): False - OAuth doesn't use password in provider directly
        EXTERNAL_PROVIDER (bool): True - This is an external authentication source
        PROVIDER_CONFIG_CLASS: The associated configuration class for this provider
    """
    PASSWORD_ABLE: bool = False
    EXTERNAL_PROVIDER: bool = True
    PROVIDER_CONFIG_CLASS = EntraIdAuthenticationProviderConfig

    # Cache for JWKS keys
    _jwks_cache: Optional[dict] = None
    _jwks_cache_time: Optional[datetime] = None
    JWKS_CACHE_DURATION_SECONDS = 3600  # 1 hour

    def __init__(self,
                 config: EntraIdAuthenticationProviderConfig = None,
                 security_manager: SecurityManager = None,
                 users_manager: UsersManager = None):
        """
        Initialize the Entra ID authentication provider.

        Args:
            config (EntraIdAuthenticationProviderConfig, optional): The Entra ID provider configuration
            security_manager (SecurityManager, optional): The security manager instance
            users_manager (UsersManager, optional): The users manager instance
        """
        super().__init__(config,
                         security_manager=security_manager,
                         users_manager=users_manager)


    def get_authorization_url(self, state: str = None) -> str:
        """
        Generate the Microsoft authorization URL for OAuth2 flow.

        Args:
            state (str, optional): State parameter for CSRF protection

        Returns:
            str: The full authorization URL to redirect the user to
        """
        params = {
            'client_id': self.config.client_id,
            'response_type': 'code',
            'redirect_uri': self.config.redirect_uri,
            'response_mode': 'query',
            'scope': 'openid profile email',
        }
        if state:
            params['state'] = state

        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return f"{self.config.authorize_url}?{query_string}"


    def exchange_code_for_tokens(self, authorization_code: str) -> dict:
        """
        Exchange the authorization code for access and ID tokens.

        Args:
            authorization_code (str): The authorization code received from Microsoft

        Returns:
            dict: Token response containing access_token, id_token, etc.

        Raises:
            AuthenticationError: If token exchange fails
        """
        data = {
            'client_id': self.config.client_id,
            'client_secret': self.config.client_secret,
            'code': authorization_code,
            'redirect_uri': self.config.redirect_uri,
            'grant_type': 'authorization_code',
            'scope': 'openid profile email',
        }

        try:
            response = requests.post(self.config.token_url, data=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as err:
            LOGGER.error('[exchange_code_for_tokens] Failed to exchange code: %s', err)
            raise AuthenticationError(f'Failed to exchange authorization code: {err}') from err


    def _get_jwks(self) -> dict:
        """
        Get the JWKS (JSON Web Key Set) from Microsoft, with caching.

        Returns:
            dict: The JWKS containing public keys for token validation
        """
        now = datetime.now(timezone.utc)

        # Check cache
        if (self._jwks_cache is not None and 
            self._jwks_cache_time is not None and
            (now - self._jwks_cache_time).total_seconds() < self.JWKS_CACHE_DURATION_SECONDS):
            return self._jwks_cache

        try:
            response = requests.get(self.config.jwks_uri, timeout=30)
            response.raise_for_status()
            self._jwks_cache = response.json()
            self._jwks_cache_time = now
            return self._jwks_cache
        except requests.RequestException as err:
            LOGGER.error('[_get_jwks] Failed to fetch JWKS: %s', err)
            raise AuthenticationError(f'Failed to fetch JWKS: {err}') from err


    def validate_id_token(self, id_token: str) -> dict:
        """
        Validate the ID token from Microsoft and extract claims.

        Args:
            id_token (str): The JWT ID token

        Returns:
            dict: The validated token claims

        Raises:
            AuthenticationError: If token validation fails
        """
        try:
            jwks = self._get_jwks()
            claims = jwt.decode(
                id_token,
                JsonWebKey.import_key_set(jwks),
                claims_options={
                    'iss': {'values': [
                        f"https://login.microsoftonline.com/{self.config.tenant_id}/v2.0",
                        f"https://sts.windows.net/{self.config.tenant_id}/"
                    ]},
                    'aud': {'values': [self.config.client_id]},
                }
            )
            claims.validate()
            return dict(claims)
        except (BadSignatureError, InvalidClaimError) as err:
            LOGGER.error('[validate_id_token] Token validation failed: %s', err)
            raise AuthenticationError(f'ID token validation failed: {err}') from err
        except Exception as err:
            LOGGER.error('[validate_id_token] Unexpected error: %s', err)
            raise AuthenticationError(f'Token validation error: {err}') from err


    def __map_group(self, azure_groups: list[str]) -> int:
        """
        Determine the user's group based on Azure AD group memberships.

        Args:
            azure_groups (list[str]): List of Azure AD group names the user belongs to

        Returns:
            int: The internal group ID mapped from the user's Azure AD groups
        """
        user_group = self.config.default_group
        if not self.config.groups.get('mapping') or len(self.config.groups['mapping']) == 0 or \
           len(azure_groups) == 0:
            return user_group

        mappings = self.config.groups['mapping']
        for mapping in mappings:
            if mapping['group_name'].lower() in [g.lower() for g in azure_groups]:
                try:
                    user_group = self.config.mapping(mapping['group_name'])
                    break
                except GroupMappingError:
                    continue
        return user_group


    def authenticate_with_token(self, id_token: str) -> CmdbUser:
        """
        Authenticate a user using a validated ID token from Microsoft.

        Args:
            id_token (str): The JWT ID token from Microsoft

        Returns:
            CmdbUser: The authenticated CMDB user object

        Raises:
            AuthenticationError: If authentication fails
        """
        # Validate the token and extract claims
        claims = self.validate_id_token(id_token)

        # Extract user information from claims
        user_name = claims.get('preferred_username', claims.get('email', '')).lower()
        if not user_name:
            raise AuthenticationError('No username found in token claims')

        # Get groups from claims (if available and group mapping is active)
        azure_groups = claims.get('groups', [])
        user_group_id = self.config.default_group

        if self.config.groups.get('active', False) and azure_groups:
            user_group_id = self.__map_group(azure_groups)

        try:
            # Try to find existing user
            user_instance: CmdbUser = self.users_manager.get_user_by({'user_name': user_name})

            # Update group if group mapping is active and group changed
            if (user_instance.group_id != user_group_id) and self.config.groups.get('active', False):
                user_instance.group_id = user_group_id
                try:
                    self.users_manager.update_user(user_instance.public_id, user_instance)
                    user_instance = self.users_manager.get_user_by({'user_name': user_name})
                except BaseManagerUpdateError as err:
                    raise AuthenticationError(err) from err

        except UsersManagerGetError:
            # User doesn't exist, create new user
            LOGGER.info('[authenticate_with_token] Creating new user: %s', user_name)
            try:
                new_user_data = {
                    'user_name': user_name,
                    'email': claims.get('email', user_name),
                    'first_name': claims.get('given_name', ''),
                    'last_name': claims.get('family_name', ''),
                    'active': True,
                    'group_id': int(user_group_id),
                    'registration_time': datetime.now(timezone.utc),
                    'authenticator': EntraIdAuthenticationProvider.get_name()
                }

                user_id = self.users_manager.insert_user(new_user_data)
                user_instance = self.users_manager.get_user(user_id)

                if not user_instance:
                    raise AuthenticationError("Failed to create user")

            except UsersManagerInsertError as error:
                LOGGER.error('[authenticate_with_token] Failed to create user: %s', error)
                raise AuthenticationError(error) from error

        return user_instance


    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """
        Standard authenticate method - not used for OAuth flow.
        
        For Entra ID, use authenticate_with_token() instead after completing
        the OAuth2 authorization code flow.

        Raises:
            AuthenticationError: Always, as this method is not supported for OAuth
        """
        raise AuthenticationError(
            'Entra ID authentication requires OAuth flow. Use authenticate_with_token() instead.'
        )


    def is_active(self) -> bool:
        """
        Check if the Entra ID authentication provider is active and properly configured.

        Returns:
            bool: True if the provider is active and has required configuration
        """
        return (
            self.config.active and 
            bool(self.config.tenant_id) and 
            bool(self.config.client_id) and 
            bool(self.config.client_secret) and
            bool(self.config.redirect_uri)
        )
