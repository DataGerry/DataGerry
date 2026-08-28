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

The parameters of the group-delete route: what to do with the group's users, and which group to move
them to. Unlike its siblings this is not a pager - it inherits APIParameters only for the query-string
and ``optional`` plumbing
"""
from typing import Any

from cmdb.models.group_model import GroupDeleteMode
from cmdb.interface.rest_api.responses.response_parameters.api_parameters import APIParameters
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import ParameterKey
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                            GroupDeletionParameters - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class GroupDeletionParameters(APIParameters):
    """
    Handles parameters for deleting a group

    Parses and stores the parameters needed to delete a group: the action to perform and the id of
    another group for user reassignment if necessary
    """

    def __init__(
        self,
        query_string: str,
        action: GroupDeleteMode | None = None,
        group_id: int | str | None = None,
        **kwargs: Any
    ) -> None:
        """
        Initialises GroupDeletionParameters

        Flask's query parser delivers every value as a string, so ``group_id`` is coerced to int
        when present. A non-numeric value raises ``ValueError`` from ``int()``; the
        ``parse_parameters`` decorator catches that and aborts with HTTP 400

        Args:
            query_string (str): The raw HTTP query string. Useful when parsed parameters are insufficient
            action (GroupDeleteMode, optional): The action to perform when deleting a group
            group_id (int | str | None, optional): The public_id of another group to which users
                must be moved. Accepts ``str`` from query parsing and coerces to ``int``
            **kwargs (Any): Additional optional parameters

        Raises:
            ValueError: When ``group_id`` is provided but cannot be parsed as an integer
        """
        self.action: GroupDeleteMode | None = action
        self.group_id: int | None = int(group_id) if group_id is not None else None
        super().__init__(query_string=query_string, **kwargs)

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @staticmethod
    def to_dict(parameters: "GroupDeletionParameters") -> dict[str, Any]:
        """
        Converts an instance of `GroupDeletionParameters` to a dictionary

        Args:
            parameters (GroupDeletionParameters): The instance to convert

        Returns:
            dict[str, Any]: A dictionary representation of the group deletion parameters
        """
        return {
            ParameterKey.ACTION.value: parameters.action,
            ParameterKey.GROUP_ID.value: parameters.group_id,
            ParameterKey.OPTIONAL.value: parameters.optional,
        }
