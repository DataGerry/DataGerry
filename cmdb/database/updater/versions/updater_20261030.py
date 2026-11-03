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
Database update 20261030: make a CmdbType's SpecialType a singleton held by an index

A SpecialType (SUPERNET, SUBNET, VLAN, RACK, CABLE) is carried by at most one CmdbType - the IPAM, Rack and Port code
looks its Type up expecting exactly one. Until this version only a read guarded it, so two concurrent creates could
both pass. Since this version a partial unique index on ``special_type`` - over the Types whose marker is a non-empty
string; an ordinary Type stores null, or ``''`` - is the guarantee.

**Duplicates already stored are reported, not resolved.** Which Type should keep the marker cannot be decided here:
the objects of both Types carry the marker too, and the IPAM wiring points at both. A SpecialType cannot be changed
through the API either, so an administrator resolves a duplicate by deleting one of the Types. This update therefore
writes nothing to a Type: it logs every SpecialType held by more than one Type - each Type's id, name and number of
objects - and builds the index only when no duplicate is stored. On a database that holds one the read stays the
only guard, and the startup index reconciliation keeps logging the refusal until the duplicate is gone.

Re-run safe: it reads, reports and builds again; an index of that name that is already unique is left alone - one
that is not is dropped and rebuilt
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import ASCENDING, IndexModel

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
TYPE_COLLECTION: str = 'framework.types'
OBJECT_COLLECTION: str = 'framework.objects'
SPECIAL_TYPE_FIELD: str = 'special_type'
NAME_FIELD: str = 'name'
PUBLIC_ID_FIELD: str = 'public_id'
OBJECT_TYPE_ID_FIELD: str = 'type_id'
MONGO_ID_FIELD: str = '_id'
SPECIAL_TYPE_INDEX: str = 'special_type'
INDEX_UNIQUE_KEY: str = 'unique'
# Only a marker that is set counts - a non-empty string; an ordinary Type stores null, or '' (schema-legal, read as
# "no marker")
MARKER_IS_SET: dict[str, Any] = {SPECIAL_TYPE_FIELD: {'$gt': ''}}


def duplicate_special_types(types: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    The SpecialTypes more than one Type carries, each with its Types by public_id

    Args:
        types (list[dict[str, Any]]): The stored Types whose marker is set, each with public_id, name and marker

    Returns:
        dict[str, list[dict[str, Any]]]: SpecialType -> its Types, ascending by public_id; only the duplicated ones
    """
    by_marker: dict[str, list[dict[str, Any]]] = {}

    for a_type in types:
        marker: Any = a_type.get(SPECIAL_TYPE_FIELD)

        if isinstance(marker, str) and marker and isinstance(a_type.get(PUBLIC_ID_FIELD), int):
            by_marker.setdefault(marker, []).append(a_type)

    return {
        marker: sorted(holders, key=lambda holder: holder[PUBLIC_ID_FIELD])
        for marker, holders in by_marker.items() if len(holders) > 1
    }

# -------------------------------------------------------------------------------------------------------------------- #
# ---------------------------------------------- Update20261030 - CLASS ---------------------------------------------- #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261030(BaseDatabaseUpdate):
    """
    Reports duplicate CmdbType SpecialTypes and makes the SpecialType a singleton by index

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261030


    def description(self) -> str:
        return "Reports SpecialTypes held by more than one type and makes a type's SpecialType unique"


    def start_update(self) -> None:
        """
        Reports the duplicates, builds the index when there are none, then bumps the version

        Raises:
            UpdaterException: If a read or the index build failed
        """
        try:
            duplicates: dict[str, list[dict[str, Any]]] = self.report_duplicates()

            if duplicates:
                LOGGER.warning("[Update20261030] The unique '%s' index on %s is not built while a SpecialType is "
                               "held by more than one type: %s", SPECIAL_TYPE_INDEX, TYPE_COLLECTION,
                               sorted(duplicates))
            elif self.build_unique_special_type_index():
                LOGGER.info("[Update20261030] Built the unique '%s' index on %s", SPECIAL_TYPE_INDEX,
                            TYPE_COLLECTION)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def report_duplicates(self) -> dict[str, list[dict[str, Any]]]:
        """
        Logs every SpecialType more than one Type carries, with each Type's id, name and number of objects

        Returns:
            dict[str, list[dict[str, Any]]]: The duplicated SpecialTypes with their Types, as reported
        """
        types: list[dict[str, Any]] = list(self.dbm.find(
            TYPE_COLLECTION,
            self.db_name,
            filter=dict(MARKER_IS_SET),
            projection={PUBLIC_ID_FIELD: 1, NAME_FIELD: 1, SPECIAL_TYPE_FIELD: 1, MONGO_ID_FIELD: 0},
        ))
        duplicates: dict[str, list[dict[str, Any]]] = duplicate_special_types(types)

        for marker, holders in duplicates.items():
            LOGGER.warning("[Update20261030] The SpecialType %r is held by %d types - delete all but one: %s",
                           marker, len(holders), [self.describe_type(holder) for holder in holders])

        return duplicates


    def describe_type(self, a_type: dict[str, Any]) -> str:
        """
        One Type as the report names it: id, name and how many objects it has

        Args:
            a_type (dict[str, Any]): The Type, with its public_id and name

        Returns:
            str: E.g. ``type 12 'subnet' (40 objects)``
        """
        objects: int = self.dbm.count(OBJECT_COLLECTION, self.db_name, {OBJECT_TYPE_ID_FIELD: a_type[PUBLIC_ID_FIELD]})

        return f"type {a_type[PUBLIC_ID_FIELD]} {a_type.get(NAME_FIELD)!r} ({objects} objects)"


    def build_unique_special_type_index(self) -> bool:
        """
        Builds the partial unique index on the SpecialType, unless it is already in place

        An index of that name that is not unique is dropped first: MongoDB refuses to recreate an index under the
        same name with other options

        Returns:
            bool: True when the index was built, False when it was already unique
        """
        index_info: dict[str, Any] = dict(self.dbm.get_index_info(TYPE_COLLECTION, self.db_name))
        existing: dict[str, Any] | None = index_info.get(SPECIAL_TYPE_INDEX)

        if existing is not None and existing.get(INDEX_UNIQUE_KEY, False):
            return False

        if existing is not None:
            self.dbm.drop_index(TYPE_COLLECTION, self.db_name, SPECIAL_TYPE_INDEX)

        self.dbm.create_indexes(TYPE_COLLECTION, self.db_name, [
            IndexModel([(SPECIAL_TYPE_FIELD, ASCENDING)], name=SPECIAL_TYPE_INDEX, unique=True,
                       partialFilterExpression=dict(MARKER_IS_SET)),
        ])

        return True
