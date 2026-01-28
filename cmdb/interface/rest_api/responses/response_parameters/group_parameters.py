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
Implementation of GroupDeletionParameters
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.group_model import GroupDeleteMode
from cmdb.interface.rest_api.responses.response_parameters.api_parameters import APIParameters
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            GroupDeletionParameters - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class GroupDeletionParameters(APIParameters):
    """
    Handles parameters for deleting a group
    
    This class parses and stores the parameters needed to delete a group, including the action to perform
    and the ID of another group for user reassignment if necessary.
    """

    def __init__(
        self,
        query_string: str,
        action: GroupDeleteMode | None = None,
        group_id: int | None = None,
        **kwargs
    ) -> None:
        """
        Initialises GroupDeletionParameters

        Args:
            query_string (str): The raw HTTP query string. Useful when parsed parameters are insufficient
            action (GroupDeleteMode, optional): The action to perform when deleting a group
            group_id (int, optional): The public ID of another group to which users must be moved
            **kwargs: Additional optional parameters
        """
        self.action = action
        self.group_id: int = group_id
        super().__init__(query_string = query_string, **kwargs)

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, query_string: str, **optional) -> "GroupDeletionParameters":
        """
        Creates GroupDeletionParameters from an HTTP query string

        Args:
            query_string (str): The raw HTTP query string
            **optional: Additional optional parameters

        Returns:
            GroupDeletionParameters: A new instance populated with the provided data
        """
        return cls(query_string, **optional)


    @classmethod
    def to_dict(cls, parameters: "GroupDeletionParameters") -> dict[str, Any]:
        """
        Converts an instance of `GroupDeletionParameters` to a dictionary

        Args:
            parameters (GroupDeletionParameters): The instance to convert

        Returns:
            dict: A dictionary representation of the group deletion parameters
        """
        return {
            "action": parameters.action,
            "group_id": parameters.group_id,
            "optional": parameters.optional
        }
