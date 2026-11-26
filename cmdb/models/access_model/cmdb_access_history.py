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
Implementation of CmdbAccessHistory in DataGerry

One entry of the access change history: one changed access document - who changed it, when, how, before and after,
why (the comment) and which user groups it concerns. Written by the server only; never changed
"""
from datetime import datetime
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.access_model.cmdb_access_history_schema import get_cmdb_access_history_schema
from cmdb.models.access_model.access_history_constants import AccessHistoryKey

from cmdb.errors.models.cmdb_access_history import (
    CmdbAccessHistoryInitError,
    CmdbAccessHistoryInitFromDataError,
    CmdbAccessHistoryToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                              CmdbAccessHistory - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbAccessHistory(CmdbDAO):
    """
    Implementation of CmdbAccessHistory

    Extends: CmdbDAO
    """
    COLLECTION = 'access.history'
    INIT_FROM_DATA_ERROR: type[Exception] = CmdbAccessHistoryInitFromDataError
    TO_JSON_ERROR: type[Exception] = CmdbAccessHistoryToJsonError
    INDEX_KEYS = [
        {'keys': [(AccessHistoryKey.TIME.value, CmdbDAO.DAO_DESCENDING),
                  (AccessHistoryKey.PUBLIC_ID.value, CmdbDAO.DAO_DESCENDING)], 'name': 'time_public_id'},
        {'keys': [(AccessHistoryKey.GROUP_IDS.value, CmdbDAO.DAO_ASCENDING),
                  (AccessHistoryKey.TIME.value, CmdbDAO.DAO_DESCENDING)], 'name': 'group_ids_time'},
        {'keys': [(AccessHistoryKey.KIND.value, CmdbDAO.DAO_ASCENDING),
                  (AccessHistoryKey.DOCUMENT_ID.value, CmdbDAO.DAO_ASCENDING),
                  (AccessHistoryKey.TIME.value, CmdbDAO.DAO_DESCENDING)], 'name': 'kind_document_time'},
    ]

    SCHEMA: dict[str, Any] = get_cmdb_access_history_schema()


    # pylint: disable=too-many-arguments
    def __init__(self, *, public_id: int, time: datetime, user_id: int | None, user_name: str | None, action: str,
                 kind: str, document_id: Any, before: dict[str, Any] | None, after: dict[str, Any] | None,
                 changed: list[str], group_ids: list[int], source: str, comment: str | None = None) -> None:
        """
        Initialises a CmdbAccessHistory entry

        Args:
            public_id (int): public_id of the entry
            time (datetime): When the change was written (UTC)
            user_id (int | None): Who made it
            user_name (str | None): Their name as it was then
            action (str): ``HistoryAction`` value
            kind (str): ``HistoryKind`` value
            document_id (Any): The changed document's id
            before (dict[str, Any] | None): The document before; None for a create
            after (dict[str, Any] | None): The document after; None for a delete
            changed (list[str]): The top-level keys that differ
            group_ids (list[int]): The user groups the change concerns
            source (str): ``HistorySource`` value
            comment (str | None): The writer's comment. Defaults to None

        Raises:
            CmdbAccessHistoryInitError: When the entry could not be initialised
        """
        try:
            self.time: datetime = time
            self.user_id: int | None = user_id
            self.user_name: str | None = user_name
            self.action: str = action
            self.kind: str = kind
            self.document_id: Any = document_id
            self.before: dict[str, Any] | None = before
            self.after: dict[str, Any] | None = after
            self.changed: list[str] = list(changed or [])
            self.group_ids: list[int] = list(group_ids or [])
            self.source: str = source
            self.comment: str | None = comment

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbAccessHistoryInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbAccessHistory":
        """
        Initialises a CmdbAccessHistory entry from a dict

        Args:
            data (dict[str, Any]): The stored entry

        Raises:
            CmdbAccessHistoryInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbAccessHistory: The entry
        """
        try:
            return cls(**{key.value: data.get(key.value) for key in AccessHistoryKey})
        except Exception as err:
            raise CmdbAccessHistoryInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbAccessHistory") -> dict[str, Any]:
        """
        Converts a CmdbAccessHistory entry into a json compatible dict

        Args:
            instance (CmdbAccessHistory): The entry

        Raises:
            CmdbAccessHistoryToJsonError: If the entry could not be converted

        Returns:
            dict[str, Any]: The entry as stored
        """
        try:
            return {key.value: (instance.get_public_id() if key is AccessHistoryKey.PUBLIC_ID
                                else getattr(instance, key.value)) for key in AccessHistoryKey}
        except Exception as err:
            raise CmdbAccessHistoryToJsonError(err) from err
