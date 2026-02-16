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
Implementation of CmdbAuthSettings
"""
from logging import Logger, getLogger

from cmdb.errors.models.cmdb_auth_settings import AuthSettingsInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

DEFAULT_TOKEN_LIFETIME = 1400

# -------------------------------------------------------------------------------------------------------------------- #
#                                               CmdbAuthSettings - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbAuthSettings:
    """
    This class stores all required data for an authentification
    """
    #TODO: REFACTOR-FIX

    def __init__(
            self,
            _id : str = None,
            providers: list[dict] = None,
            enable_external: bool = False,
            token_lifetime: int = DEFAULT_TOKEN_LIFETIME
        ):
        """
        Creates an instance of CmdbAuthSettings
        
        Args:
            _id (str, optional): _description_. Defaults to None.
            providers (list[dict], optional): _description_. Defaults to None.
            enable_external (bool, optional): _description_. Defaults to False.
            token_lifetime (int, optional): _description_. Defaults to None.

        Raises:
            AuthSettingsInitError: When the CmdbAuthSettings could not be initialised
        """
        try:
            self._id = _id or 'auth'
            self.providers = providers or []
            self.token_lifetime = token_lifetime
            self.enable_external = enable_external
        except Exception as err:
            raise AuthSettingsInitError(err) from err


    def get_id(self) -> str:
        """
        Retrieves the unique identifier of the instance

        Returns:
            str: The unique ID associated with this instance
        """
        return self._id


    def get_token_lifetime(self) -> int:
        """
        Returns the value of the token_lifetime property

        Returns:
            int: The token_lifetime of this CmdbAuthSettings 
        """
        return self.token_lifetime


    def get_provider_list(self) -> list[dict]:
        """
        Get the list of providers with config
        """
        return self.providers


    def get_provider_settings(self, class_name: str) -> dict:
        """
        Get a specific provider list element by name
        """
        return next(config for config in self.get_provider_list() if config['class_name'] == class_name)['config']
