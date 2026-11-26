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
The field classes of a Type's fields, read once per request (phase 12, P1)

A field's class is stored on its definition (``FieldKey.PROTECTION``) - on the Type, a global template's copy
included. The access decision needs it for the fields a write changes: one projected read per Type and request
"""
from typing import Any

from cmdb.utils import request_cache
from cmdb.manager import TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import SYSTEM_FIELD_CLASS
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'FIELD_CLASSES_CACHE_KEY',
    'classes_of_fields',
    'system_field_names',
    'type_field_classes',
]

# The request cache the classes of each Type are kept under
FIELD_CLASSES_CACHE_KEY: str = 'type-field-classes'
_PROJECTION: dict[str, int] = {'_id': 0, f'{TypeSchemaKey.FIELDS.value}.{FieldKey.NAME.value}': 1,
                               f'{TypeSchemaKey.FIELDS.value}.{FieldKey.PROTECTION.value}': 1}


def classes_of_fields(fields: Any) -> dict[str, str]:
    """
    The classed fields of a field definition list - pure

    Args:
        fields (Any): A Type's ``fields``

    Returns:
        dict[str, str]: ``{field name: class}`` for every field carrying a class
    """
    return {field[FieldKey.NAME.value]: field[FieldKey.PROTECTION.value] for field in fields or []
            if isinstance(field, dict) and isinstance(field.get(FieldKey.NAME.value), str)
            and isinstance(field.get(FieldKey.PROTECTION.value), str) and field[FieldKey.PROTECTION.value]}


def system_field_names(fields: Any) -> set[str]:
    """
    The fields of the ``system`` class in a field definition list - only the server writes them - pure

    Args:
        fields (Any): A Type's ``fields``

    Returns:
        set[str]: Their names
    """
    return {name for name, field_class in classes_of_fields(fields).items() if field_class == SYSTEM_FIELD_CLASS}


def type_field_classes(user: CmdbUser, type_id: Any) -> dict[str, str]:
    """
    The classed fields of a Type, once per request

    Args:
        user (CmdbUser): The user the request is made for - names the tenant
        type_id (Any): The Type; anything that is no id has none

    Raises:
        TypesManagerGetError | BaseManagerGetError: When the Type could not be read

    Returns:
        dict[str, str]: ``{field name: class}``; empty for a Type without classed fields, or none
    """
    if not isinstance(type_id, int) or isinstance(type_id, bool):
        return {}

    cache: dict[Any, Any] | None = request_cache(FIELD_CLASSES_CACHE_KEY)
    key: tuple[Any, ...] = (ManagerProvider.tenant_database(user), type_id)

    if cache is not None and key in cache:
        return cache[key]

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, user)
    found: list[dict[str, Any]] = types_manager.find(criteria={TypeSchemaKey.PUBLIC_ID.value: type_id},
                                                     projection=_PROJECTION)
    classes: dict[str, str] = classes_of_fields(found[0].get(TypeSchemaKey.FIELDS.value)) if found else {}

    if cache is not None:
        cache[key] = classes

    return classes
