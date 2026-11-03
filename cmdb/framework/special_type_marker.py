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
The SpecialType marker of an object's CmdbType, from a type the caller already holds or from the database

The IPAM and Rack checks of an object write each ask "what special type is this object's type?". An update has
already resolved the type when they run, so they take it as ``object_type`` and read nothing; a caller without one
(the create, the imports) gets the read as before
"""
from typing import Any

from cmdb.manager import TypesManager
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

def read_special_type_marker(types_manager: TypesManager, type_id: int, object_type: CmdbType | None = None) -> Any:
    """
    Returns the raw ``special_type`` marker of a CmdbType, None for a type without one or a type that does not exist

    Args:
        types_manager (TypesManager): db interface for CmdbTypes, read only when ``object_type`` does not answer
        type_id (int): public_id of the CmdbType
        object_type (CmdbType | None): The type already resolved by the caller - used only when it IS ``type_id``

    Returns:
        Any: The stored marker as it is (validity is the caller's question), or None
    """
    if object_type is not None and object_type.public_id == type_id:
        return object_type.special_type

    type_doc: dict[str, Any] | None = types_manager.get_type(type_id)

    return type_doc.get(TypeSchemaKey.SPECIAL_TYPE.value) if type_doc else None
