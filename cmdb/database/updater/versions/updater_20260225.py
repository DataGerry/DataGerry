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
Database update 20260225: backfill the field 'type' property on object fields
"""
from logging import Logger, getLogger
from collections import defaultdict
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260225 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260225(BaseDatabaseUpdate):
    """
    Backfills the 'type' property onto every object field (and MDS field) from its type schema
    """
    def creation_date(self) -> int:
        return 20260225


    def description(self) -> str:
        return "Adds the 'type' property to all object fields"


    def start_update(self) -> None:
        """
        Backfills the field 'type' property onto all objects, then bumps the updater version
        """
        try:
            self.backfill_object_field_types()

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def build_field_type_map_by_type(self) -> dict[int, dict[str, str]]:
        """
        Builds a per-type lookup of field name -> field type from every CmdbType schema

        Returns:
            dict[int, dict[str, str]]: Maps a type's public_id to a {field_name: field_type} map, e.g.
                {32: {"ref-391f8254...": "ref", "text-f96955e2...": "text"}, 33: {...}}
        """
        types: list[dict[str, Any]] = self.types_manager.find(criteria={})

        mapping: dict[int, dict[str, str]] = {}

        for t in types:
            type_id = t["public_id"]
            mapping[type_id] = {}

            for field in t["fields"]:
                mapping[type_id][field["name"]] = field["type"]

        return mapping


    def backfill_object_field_types(self) -> None:
        """
        Backfills the 'type' property into every object's fields[] (and MDS data) entries

        For each type, the field names are grouped by their schema field type and bulk-updated on the
        matching objects via self.objects_manager, only where the field's 'type' is not already set.

        Raises:
            UpdaterException: If the backfill fails
        """
        try:
            mapping_by_type = self.build_field_type_map_by_type()

            for type_id, field_map in mapping_by_type.items():
                by_field_type: dict[str, list[str]] = defaultdict(list)

                for field_name, field_type in field_map.items():
                    by_field_type[field_type].append(field_name)

                # Update normal fields
                for field_type, names in by_field_type.items():
                    self.objects_manager.update_many_raw(
                        filter_query={
                            "type_id": type_id,
                            "fields": {
                                "$elemMatch": {
                                    "name": {"$in": names},
                                    "type": {"$exists": False},
                                }
                            },
                        },
                        update={
                            "$set": {
                                "fields.$[f].type": field_type
                            }
                        },
                        array_filters=[
                            {
                                "f.name": {"$in": names},
                                "f.type": {"$exists": False},
                            }
                        ],
                    )

                    # Update MDS fields
                    self.objects_manager.update_many_raw(
                        filter_query={
                            "type_id": type_id,
                            "multi_data_sections.values.data": {
                                "$elemMatch": {
                                    "name": {"$in": names},
                                    "type": {"$exists": False},
                                }
                            },
                        },
                        update={
                            "$set": {
                                "multi_data_sections.$[].values.$[].data.$[f].type": field_type
                            }
                        },
                        array_filters=[
                            {
                                "f.name": {"$in": names},
                                "f.type": {"$exists": False},
                            }
                        ],
                    )
        except Exception as err:
            raise UpdaterException(
                f"Failed to backfill field types into objects: {err}"
            ) from err
