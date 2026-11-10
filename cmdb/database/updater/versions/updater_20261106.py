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
Database update 20261106: every object field entry carries the type its field declares

An object stores each field as ``{name, value, type}``. The ``type`` was copied once, when the entry was created, and
never followed the type again: a field that changed its type (in the UI: deleted and dropped again as another control
under the same identifier, in one save) kept the old one on every object, and an object write stored whatever ``type``
the client sent. This update sets every entry's ``type`` - flat and in every multi-data-section row - to the one its
type declares. **The values are kept**: which entries a type change left behind can no longer be told from those a
client wrote, so nothing is cleared here; a type change from now on resets the values itself.

One pipeline update per type, nothing read into Python but the types' field lists. An entry of a field the type does
not declare, and anything that is not an array where a list belongs, is left as it is.

Re-run safe: the update only sets ``type`` to the declared one - a second run writes the same values, so MongoDB
modifies no document
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateMany

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
TYPES_COLLECTION: str = 'framework.types'
OBJECTS_COLLECTION: str = 'framework.objects'
TYPE_PUBLIC_ID_FIELD: str = 'public_id'
TYPE_FIELDS_FIELD: str = 'fields'
OBJECT_TYPE_ID_FIELD: str = 'type_id'
OBJECT_FIELDS_FIELD: str = 'fields'
OBJECT_MDS_FIELD: str = 'multi_data_sections'
MDS_VALUES_FIELD: str = 'values'
MDS_ROW_DATA_FIELD: str = 'data'
ENTRY_NAME_KEY: str = 'name'
ENTRY_TYPE_KEY: str = 'type'
FALLBACK_FIELD_TYPE: str = 'text'

TYPE_FIELDS_PROJECTION: dict[str, int] = {TYPE_PUBLIC_ID_FIELD: 1, TYPE_FIELDS_FIELD: 1}

# -------------------------------------------------------------------------------------------------------------------- #

def map_if_array(path: str, variable: str, expression: Any) -> dict[str, Any]:
    """
    ``$map`` over an array, leaving anything that is not one exactly as it is

    Args:
        path (str): The array's ``$`` / ``$$`` path
        variable (str): The name the element is bound to
        expression (Any): What each element becomes

    Returns:
        dict[str, Any]: The aggregation expression
    """
    return {'$cond': [{'$isArray': path}, {'$map': {'input': path, 'as': variable, 'in': expression}}, path]}


def stamped_entry(variable: str, names: list[str], kinds: list[str]) -> dict[str, Any]:
    """
    One entry with its declared type set, its value kept; an undeclared entry unchanged

    Args:
        variable (str): The name the entry is bound to
        names (list[str]): The declared field names
        kinds (list[str]): Their types, in the same order

    Returns:
        dict[str, Any]: The aggregation expression
    """
    entry: str = f'$${variable}'
    name: str = f'{entry}.{ENTRY_NAME_KEY}'
    declared_kind: dict[str, Any] = {
        '$arrayElemAt': [{'$literal': kinds}, {'$indexOfArray': [{'$literal': names}, name]}],
    }

    return {'$cond': [
        {'$in': [name, {'$literal': names}]},
        {'$mergeObjects': [entry, {ENTRY_TYPE_KEY: declared_kind}]},
        entry,
    ]}


def build_stamp_operation(type_document: dict[str, Any]) -> UpdateMany | None:
    """
    The update that stamps every object of one type, flat entries and MDS rows

    Args:
        type_document (dict[str, Any]): A stored type, projected to its public_id and fields

    Returns:
        UpdateMany | None: The update; None for a type that declares no usable field
    """
    declared: list[dict[str, Any]] = [
        field for field in type_document.get(TYPE_FIELDS_FIELD) or []
        if isinstance(field, dict) and isinstance(field.get(ENTRY_NAME_KEY), str)
    ]

    if not declared:
        return None

    names: list[str] = [field[ENTRY_NAME_KEY] for field in declared]
    kinds: list[str] = [field.get(ENTRY_TYPE_KEY) or FALLBACK_FIELD_TYPE for field in declared]

    row_data: dict[str, Any] = map_if_array(
        f'$$row.{MDS_ROW_DATA_FIELD}', 'entry', stamped_entry('entry', names, kinds),
    )
    rows: dict[str, Any] = map_if_array(f'$$section.{MDS_VALUES_FIELD}', 'row', {'$mergeObjects': [
        '$$row', {MDS_ROW_DATA_FIELD: row_data},
    ]})

    return UpdateMany(
        {OBJECT_TYPE_ID_FIELD: type_document[TYPE_PUBLIC_ID_FIELD]},
        [{'$set': {
            OBJECT_FIELDS_FIELD: map_if_array(f'${OBJECT_FIELDS_FIELD}', 'field', stamped_entry('field', names, kinds)),
            OBJECT_MDS_FIELD: map_if_array(f'${OBJECT_MDS_FIELD}', 'section', {'$mergeObjects': [
                '$$section', {MDS_VALUES_FIELD: rows},
            ]}),
        }}],
    )

# ---------------------------------------------- Update20261106 - CLASS ---------------------------------------------- #

class Update20261106(BaseDatabaseUpdate):
    """
    Sets every object field entry's type to the one its field declares, keeping the values

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261106


    def description(self) -> str:
        return "Sets every object field entry's type to the type its field declares"


    def start_update(self) -> None:
        """
        Reads the types' field lists, stamps the objects of each one, then bumps the version

        Raises:
            UpdaterException: If the read or an update fails
        """
        try:
            operations: list[UpdateMany] = [
                operation
                for operation in (
                    build_stamp_operation(type_document)
                    for type_document in self.dbm.find(
                        collection=TYPES_COLLECTION,
                        db_name=self.db_name,
                        filter={},
                        projection=TYPE_FIELDS_PROJECTION,
                    )
                    if isinstance(type_document.get(TYPE_PUBLIC_ID_FIELD), int)
                )
                if operation is not None
            ]

            if operations:
                self.dbm.bulk_write(OBJECTS_COLLECTION, self.db_name, operations)

            LOGGER.info("[updater_20261106] Stamped the field types of the objects of %s type(s)", len(operations))

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
