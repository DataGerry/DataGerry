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
Implementation of EntraIdAuthenticationProviderConfig
"""
import logging

from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig
from cmdb.security.encryption_manager import EncryptionManager

from cmdb.errors.provider import GroupMappingError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                       EntraIdAuthenticationProviderConfig - CLASS                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class EntraIdAuthenticationProviderConfig(BaseAuthProviderConfig):
    """
    Configuration class for the Entra ID (Azure AD) Authentication Provider.

    This class holds all settings needed to connect to Microsoft Entra ID,
    authenticate users via OAuth2/OIDC, and optionally map Azure AD groups 
    to internal application groups.

    Extends: BaseAuthProviderConfig
    """
    DEFAULT_CONFIG_VALUES = {
        'active': False,
        'default_group': 2,
        'tenant_id': '',
        'client_id': '',
        'client_secret': '',
        'redirect_uri': '',
        'groups': {
            'active': False,
            'mapping': []
        }
    }

    def __init__(
        self,
        active: bool = None,
        default_group: int = None,
        tenant_id: str = None,
        client_id: str = None,
        client_secret: str = None,
        redirect_uri: str = None,
        groups: dict = None,
        *args, **kwargs):
        """
        Initialize an Entra ID Authentication Provider Configuration instance

        Args:
            active (bool, optional): Whether the Entra ID provider is active. Defaults to False
            default_group (int, optional): Default group ID for new users. Defaults to 2
            tenant_id (str, optional): Azure AD Tenant ID
            client_id (str, optional): Application (client) ID from Azure portal
            client_secret (str, optional): Client secret value
            redirect_uri (str, optional): OAuth2 callback URL
            groups (dict, optional): Group mapping settings
        """
        active = active or False
        self.default_group = int(default_group or EntraIdAuthenticationProviderConfig.
                                 DEFAULT_CONFIG_VALUES.get('default_group'))
        self.tenant_id: str = tenant_id or EntraIdAuthenticationProviderConfig. \
            DEFAULT_CONFIG_VALUES.get('tenant_id')
        self.client_id: str = client_id or EntraIdAuthenticationProviderConfig. \
            DEFAULT_CONFIG_VALUES.get('client_id')
        self._client_secret: str = client_secret or EntraIdAuthenticationProviderConfig. \
            DEFAULT_CONFIG_VALUES.get('client_secret')
        self.redirect_uri: str = redirect_uri or EntraIdAuthenticationProviderConfig. \
            DEFAULT_CONFIG_VALUES.get('redirect_uri')
        self.groups: dict = groups or EntraIdAuthenticationProviderConfig. \
            DEFAULT_CONFIG_VALUES.get('groups')

        super().__init__(active)


    @property
    def authority_url(self) -> str:
        """
        Get the Microsoft authority URL for this tenant

        Returns:
            str: The authority URL (e.g., https://login.microsoftonline.com/{tenant_id})
        """
        return f"https://login.microsoftonline.com/{self.tenant_id}"


    @property
    def token_url(self) -> str:
        """
        Get the token endpoint URL

        Returns:
            str: The token endpoint URL
        """
        return f"{self.authority_url}/oauth2/v2.0/token"


    @property
    def authorize_url(self) -> str:
        """
        Get the authorization endpoint URL

        Returns:
            str: The authorization endpoint URL
        """
        return f"{self.authority_url}/oauth2/v2.0/authorize"


    @property
    def jwks_uri(self) -> str:
        """
        Get the JWKS (JSON Web Key Set) URI for token validation

        Returns:
            str: The JWKS URI
        """
        return f"{self.authority_url}/discovery/v2.0/keys"


    def mapping(self, group_name: str) -> int:
        """
        Get the internal group ID mapped to a specific Azure AD group name

        Args:
            group_name (str): The name of the Azure AD group

        Raises:
            GroupMappingError: If no mapping is found for the given group name

        Returns:
            int: The corresponding internal group ID
        """
        try:
            return next(int(group['group_id']) for group in self.groups['mapping'] if
                        group['group_name'].lower() == group_name.lower())
        except StopIteration as err:
            raise GroupMappingError(err) from err


    @property
    def client_secret(self) -> str:
        """
        Returns the decrypted client secret
        """
        return EncryptionManager().decrypt(self._client_secret)

    @client_secret.setter
    def client_secret(self, value: str):
        """
        Sets the raw client secret (potentially encrypted if coming from DB)
        """
        self._client_secret = value
