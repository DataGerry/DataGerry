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
The dashboard chart's groups: per-type object counts labelled from their CmdbTypes

``GET /objects/group/type_id`` counts the objects per type in one aggregation and reads every group's type in one
lookup; this module turns the two into the chart's rows
"""
from typing import Any

from cmdb.models.type_model import CmdbType

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectGroupKey
# -------------------------------------------------------------------------------------------------------------------- #

def label_type_groups(groups: list[dict[str, Any]], type_map: dict[int, CmdbType], cap: int) -> list[dict[str, Any]]:
    """
    Labels per-type count groups with their type's label and colour, skipping groups whose type is gone

    A group whose type_id names no type (objects of a deleted type) has nothing to label it with and is left out; it
    does not take one of the ``cap`` places. The groups keep their order (largest first)

    Args:
        groups (list[dict[str, Any]]): ``{_id: type_id, count}`` per type, largest first
        type_map (dict[int, CmdbType]): The groups' types by public_id (missing ones absent)
        cap (int): The most groups to answer

    Returns:
        list[dict[str, Any]]: At most ``cap`` new ``{_id, count, label, type_color}`` dicts
    """
    labelled: list[dict[str, Any]] = []

    for group in groups:
        group_type: CmdbType | None = type_map.get(group[ObjectGroupKey.ID.value])

        if group_type is None:
            continue

        labelled.append({
            ObjectGroupKey.ID.value: group[ObjectGroupKey.ID.value],
            ObjectGroupKey.COUNT.value: group[ObjectGroupKey.COUNT.value],
            ObjectGroupKey.LABEL.value: group_type.label,
            ObjectGroupKey.TYPE_COLOR.value: group_type.ci_explorer_color,
        })

        if len(labelled) == cap:
            break

    return labelled
