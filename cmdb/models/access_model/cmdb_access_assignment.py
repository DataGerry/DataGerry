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
Implementation of CmdbAccessAssignment in DataGerry

An assignment grants a user group a scope role within a scope. The scope is the unconditional ``UNCONDITIONAL_SCOPE``
until the scope compiler brings the conditions; one group, role and scope are stored once
"""
from typing import Any
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.access_model.cmdb_access_assignment_schema import get_cmdb_access_assignment_schema
from cmdb.models.access_model.access_constants import (
    ASSIGNMENT_GROUP_INDEX_NAME,
    ASSIGNMENT_ROLE_INDEX_NAME,
    ASSIGNMENT_UNIQUE_INDEX_NAME,
    UNCONDITIONAL_SCOPE,
    AccessAssignmentKey,
)

from cmdb.errors.models.cmdb_access_assignment import (
    CmdbAccessAssignmentInitError,
    CmdbAccessAssignmentInitFromDataError,
    CmdbAccessAssignmentToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             CmdbAccessAssignment - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbAccessAssignment(CmdbDAO):
    """
    Implementation of CmdbAccessAssignment

    Extends: CmdbDAO
    """
    COLLECTION = 'access.assignments'
    # What its own from_data / to_json raise - declared so a manager can tell a document that no longer
    # fits the model from a programming error (GenericManager._model_errors)
    INIT_FROM_DATA_ERROR: type[Exception] = CmdbAccessAssignmentInitFromDataError
    TO_JSON_ERROR: type[Exception] = CmdbAccessAssignmentToJsonError
    INDEX_KEYS = [
        # A group's assignments in public_id order - the group delete, the group usage and the list's group filter
        {
            'keys': [(AccessAssignmentKey.GROUP_ID.value, CmdbDAO.DAO_ASCENDING),
                     (CmdbDAO.PUBLIC_ID_KEY, CmdbDAO.DAO_ASCENDING)],
            'name': ASSIGNMENT_GROUP_INDEX_NAME,
        },
        # A role's assignments in public_id order - the role delete, the role usage and the list's role filter
        {
            'keys': [(AccessAssignmentKey.ROLE_ID.value, CmdbDAO.DAO_ASCENDING),
                     (CmdbDAO.PUBLIC_ID_KEY, CmdbDAO.DAO_ASCENDING)],
            'name': ASSIGNMENT_ROLE_INDEX_NAME,
        },
        # One group, role and scope are stored once
        {
            'keys': [
                (AccessAssignmentKey.GROUP_ID.value, CmdbDAO.DAO_ASCENDING),
                (AccessAssignmentKey.ROLE_ID.value, CmdbDAO.DAO_ASCENDING),
                (AccessAssignmentKey.SCOPE.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': ASSIGNMENT_UNIQUE_INDEX_NAME,
            'unique': True,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_access_assignment_schema()


    def __init__(
        self,
        *,
        public_id: int,
        group_id: int,
        role_id: int,
        scope: Any = UNCONDITIONAL_SCOPE,
        description: str = '',
    ) -> None:
        """
        Initialises a CmdbAccessAssignment

        Args:
            public_id (int): public_id of the CmdbAccessAssignment
            group_id (int): public_id of the CmdbUserGroup it grants to
            role_id (int): public_id of the CmdbScopeRole it grants
            scope (Any): The objects it applies to. Defaults to ``UNCONDITIONAL_SCOPE``
            description (str): What the assignment is for. Defaults to ''

        Raises:
            CmdbAccessAssignmentInitError: When the CmdbAccessAssignment could not be initialised
        """
        try:
            self.group_id: int = group_id
            self.role_id: int = role_id
            self.scope: Any = scope
            self.description: str = description or ''

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbAccessAssignmentInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbAccessAssignment":
        """
        Initialises a CmdbAccessAssignment from a dict

        Args:
            data (dict[str, Any]): Data with which the CmdbAccessAssignment should be initialised

        Raises:
            CmdbAccessAssignmentInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbAccessAssignment: CmdbAccessAssignment with the given data
        """
        try:
            return cls(
                public_id=data.get(AccessAssignmentKey.PUBLIC_ID.value),
                group_id=data.get(AccessAssignmentKey.GROUP_ID.value),
                role_id=data.get(AccessAssignmentKey.ROLE_ID.value),
                scope=data.get(AccessAssignmentKey.SCOPE.value, UNCONDITIONAL_SCOPE),
                description=data.get(AccessAssignmentKey.DESCRIPTION.value, ''),
            )
        except Exception as err:
            raise CmdbAccessAssignmentInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbAccessAssignment") -> dict[str, Any]:
        """
        Converts a CmdbAccessAssignment into a json compatible dict

        Args:
            instance (CmdbAccessAssignment): The CmdbAccessAssignment which should be converted

        Raises:
            CmdbAccessAssignmentToJsonError: If the CmdbAccessAssignment could not be converted to a json compatible
                dict

        Returns:
            dict[str, Any]: Json compatible dict of the CmdbAccessAssignment values
        """
        try:
            return {
                AccessAssignmentKey.PUBLIC_ID.value: instance.get_public_id(),
                AccessAssignmentKey.GROUP_ID.value: instance.group_id,
                AccessAssignmentKey.ROLE_ID.value: instance.role_id,
                AccessAssignmentKey.SCOPE.value: instance.scope,
                AccessAssignmentKey.DESCRIPTION.value: instance.description,
            }
        except Exception as err:
            raise CmdbAccessAssignmentToJsonError(err) from err
