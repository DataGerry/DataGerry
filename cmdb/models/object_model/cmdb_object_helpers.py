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
Pure helpers that operate on a CmdbObject in its dict / document form

These are used wherever the application reads a CmdbObject through the manager layer's
``as_dict=True`` path (overviews, validators, enforcement guards) — i.e. on the BSON-shaped
document, not on the CmdbObject Python instance. Every helper here is stateless and free of
DB access so it remains unit-testable in isolation. The companion CmdbObjectKey /
CmdbObjectFieldKey / CmdbObjectMdsKey / CmdbObjectMdsRowKey enums in this package supply the
schema keys; bare string literals must not appear in new code that consumes these documents
"""
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
# -------------------------------------------------------------------------------------------------------------------- #


def extract_field_value(obj_dict: dict[str, Any], field_name: str) -> Any:
    """
    Returns the 'value' of the first entry in obj_dict's 'fields' list whose 'name' matches

    Robust against partial / drifted documents: a missing 'fields' key, a 'fields' value of
    None, an empty list, an entry without a 'name' key, or an entry without a 'value' key all
    surface as None rather than raising. When multiple entries share the same name the first
    encounter wins (callers should treat duplicates as a data-integrity issue, not rely on
    this for deduplication)

    Args:
        obj_dict (dict[str, Any]): A CmdbObject document (typically loaded via
            ObjectsManager.find_objects(..., as_dict=True))
        field_name (str): The field 'name' to look up (commonly an IPAM SubnetField /
            SupernetField / VlanField enum member, but any string works)

    Returns:
        Any: The matching field's 'value', or None when no matching field exists or the value
            is itself None
    """
    for field in obj_dict.get(CmdbObjectKey.FIELDS, []) or []:
        if field.get(CmdbObjectFieldKey.NAME) == field_name:
            return field.get(CmdbObjectFieldKey.VALUE)

    return None
