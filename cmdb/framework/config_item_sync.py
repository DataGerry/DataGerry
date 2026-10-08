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
The ConfigItem count the DataGerry service portal is told about (cloud mode)

Every object write that changes how many CmdbObjects exist reports the new count, with a per-type breakdown, so the
portal can hold the subscription's ConfigItem limit against it. The object routes and the object importer both
report, which is why the two functions live here rather than beside either of them: the framework layer may be
imported by the routes and by the importer alike, and imports no route itself
"""
from typing import Any

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager, DgServicePortalManager
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.framework.config_item_sync_constants import ConfigItemTypeCountKey
# -------------------------------------------------------------------------------------------------------------------- #


def build_type_object_counts(request_user: CmdbUser) -> tuple[list[dict[str, Any]], int]:
    """
    Builds the per-type object-count list for the Service Portal sync payload

    Counts every CmdbObject grouped by its type_id in a single aggregation, then resolves each
    type_id to its CmdbType label via one bulk lookup. CmdbTypes with no objects are omitted, and
    a counted type_id whose CmdbType no longer exists is skipped - so the returned breakdown may
    sum to less than the total. The total is taken from the same aggregation and counts every
    document (no active filter), so it always equals an unfiltered ``count_documents()``

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        tuple[list[dict[str, Any]], int]: Entries shaped ``{"name": <type label>, "count": <int>}``
            and the exact total number of CmdbObjects
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    counts_by_type, total_count = objects_manager.count_objects_grouped_by_type_with_total()

    if not counts_by_type:
        return [], total_count

    types_lookup: dict[int, CmdbType] = types_manager.get_types_lookup(list(counts_by_type.keys()))

    type_counts: list[dict[str, Any]] = []

    for type_id, count in counts_by_type.items():
        object_type: CmdbType | None = types_lookup.get(type_id)

        if object_type is None:
            continue

        type_counts.append({
            ConfigItemTypeCountKey.NAME.value: object_type.label,
            ConfigItemTypeCountKey.COUNT.value: count,
        })

    return type_counts, total_count


def handle_sync_config_item_count(request_user: CmdbUser, config_item_count: int | None = None) -> None:
    """
    Syncs the current ConfigItem count to the DataGerry service portal (cloud mode)

    Also reports the current per-type object counts (type label + count) alongside the total, so
    the portal receives a breakdown of the subscription's config items

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        config_item_count (int | None): The number of CmdbObjects to report. Omit it to take the
            total from the same aggregation that builds the breakdown - the caller then pays for
            one aggregation instead of an aggregation plus a full-collection count, and both
            numbers come from the same read
    """
    type_counts, total_count = build_type_object_counts(request_user)

    DgServicePortalManager().sync_config_items(
        request_user,
        total_count if config_item_count is None else config_item_count,
        type_counts,
    )
