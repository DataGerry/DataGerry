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
What the sync reads about the objects it mirrors into - shared by the engine, the pass and the lock
"""
from typing import Any

from cmdb.manager import ObjectsManager
from cmdb.models.object_model import CmdbObjectKey, SystemRefKind

from cmdb.framework.person_sync.person_sync_constants import KIND_PATH
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['synced_person_ids', 'linked_person_type_ids']


def synced_person_ids(objects_manager: ObjectsManager, object_ids: set[Any]) -> set[int]:
    """
    Reads which of the given objects are synced persons - one query on their ids, none without one

    Args:
        objects_manager (ObjectsManager): Reads the objects
        object_ids (set[Any]): The ids to judge; anything but an int is no object id

    Returns:
        set[int]: The ids of the synced persons among them
    """
    ids: list[int] = sorted(object_id for object_id in object_ids if isinstance(object_id, int))

    if not ids:
        return set()

    found: list[dict[str, Any]] = objects_manager.find(
        criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': ids}, KIND_PATH: SystemRefKind.USER.value},
        projection={CmdbObjectKey.PUBLIC_ID.value: 1},
    )

    return {document[CmdbObjectKey.PUBLIC_ID.value] for document in found}


def linked_person_type_ids(objects_manager: ObjectsManager) -> set[int]:
    """
    Reads the Types a person linked to a user lives in - one distinct read on the link index

    Args:
        objects_manager (ObjectsManager): Reads the objects

    Returns:
        set[int]: The Type ids
    """
    return set(objects_manager.get_distinct(CmdbObjectKey.TYPE_ID.value, {KIND_PATH: SystemRefKind.USER.value}))
