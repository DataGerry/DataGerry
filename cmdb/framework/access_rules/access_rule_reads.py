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
The one read every uniqueness pre-check of the access rules makes

A write pre-checks its uniqueness with this read so the caller gets a readable refusal; only the unique index holds
under concurrency, so the write's own duplicate-key failure is the final word
"""
from typing import Any

from cmdb.manager.base_manager import BaseManager
from cmdb.models.cmdb_dao import CmdbDAO
# -------------------------------------------------------------------------------------------------------------------- #

# A clash is found once one document matches - the count stops there
CLASH_COUNT_LIMIT: int = 1


def clashes(manager: BaseManager, criteria: dict[str, Any], own_id: int | None = None) -> bool:
    """
    Reports whether another stored document matches the criteria - the one being updated left out

    One count, stopped at the first match

    Args:
        manager (BaseManager): The manager of the collection
        criteria (dict[str, Any]): What a clashing document carries
        own_id (int | None): The public_id of the document being updated; None for a create

    Raises:
        BaseManagerGetError: When the count fails

    Returns:
        bool: True when such a document exists
    """
    query: dict[str, Any] = dict(criteria)

    if own_id is not None:
        query[CmdbDAO.PUBLIC_ID_KEY] = {'$ne': own_id}

    return manager.count_documents(query, limit=CLASH_COUNT_LIMIT) > 0
