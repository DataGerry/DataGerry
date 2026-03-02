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
Implementation of Update20260226
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.relation_model.cmdb_relation import CmdbRelation
from cmdb.models.object_relation_model.cmdb_object_relation import CmdbObjectRelation

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

OBJECT_LINK_COLLECTION: str = "framework.links"
# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260226 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260226(BaseDatabaseUpdate):
    """
    Implementation of Update20260226
    """
    def creation_date(self) -> int:
        return 20260226


    def description(self) -> str:
        return """
               Maps all ObjectLinks on a Relation
               """


    def start_update(self) -> None:
        try:
            object_links = list(self.dbm.find(
                collection=OBJECT_LINK_COLLECTION,
                db_name=self.db_name,
                filter={},
                projection={"primary": 1, "secondary": 1, "_id": 0}
            ))

            if object_links:
                # Get unique public_ids of Objects
                unique_object_ids: set[int] = set()
                for link in object_links:
                    unique_object_ids.add(link["primary"])
                    unique_object_ids.add(link["secondary"])

                # Fetch objects and create map for type_id
                objects_cursor = self.objects_manager.find(
                    criteria={"public_id": {"$in": list(unique_object_ids)}},
                    projection={"public_id": 1, "type_id": 1, "_id": 0}
                )

                object_type_map: dict[int, int] = {
                    obj["public_id"]: obj["type_id"]
                    for obj in objects_cursor
                }

                # Get all types
                all_types = self.types_manager.find(criteria={}, projection={"public_id": 1, "_id": 0})

                existing_type_ids = [t["public_id"] for t in all_types]

                mapper_relation_id: int = 0
                relation_collection: str = CmdbRelation.COLLECTION

                if self.dbm.count(
                    CmdbRelation.COLLECTION,
                    self.db_name,
                    criteria={"relation_name": "DgObjectLinks"}
                ) == 0:
                    # Create new relation for mapping
                    mapper_relation_data = self.get_mapper_relation(existing_type_ids)

                    mapper_relation_id: int = self.dbm.insert(
                        relation_collection,
                        self.db_name,
                        mapper_relation_data
                    )
                else:
                    # Retrieve the public_id
                    existing_relation_cursor  = self.dbm.find(
                        relation_collection,
                        self.db_name,
                        filter={"relation_name": "DgObjectLinks"},
                        projection={"public_id": 1, "_id": 0}
                    )

                    mapper_relation_data = next(existing_relation_cursor, None)

                    if not mapper_relation_data:
                        raise Exception("Mapper Relation not found!")

                    mapper_relation_id = mapper_relation_data['public_id']

                # Map all existing ObjectLinks on ObjectRelations
                relations_to_insert: list[dict[str, Any]] = []

                for link in object_links:
                    parent_id = link["primary"]
                    child_id = link["secondary"]

                    parent_type_id = object_type_map.get(parent_id)
                    child_type_id = object_type_map.get(child_id)

                    # Skip broken links
                    if parent_type_id is None or child_type_id is None:
                        continue

                    relations_to_insert.append(
                        self.get_object_relation_dict(
                            parent_id=parent_id,
                            child_id=child_id,
                            parent_type_id=parent_type_id,
                            child_type_id=child_type_id,
                            relation_id=mapper_relation_id,
                        )
                    )

                # Insert all new ObjectRelations into Database
                if relations_to_insert:
                    object_relation_collection = CmdbObjectRelation.COLLECTION

                    reserved_ids = self.dbm.reserve_public_ids(
                        object_relation_collection,
                        self.db_name,
                        amount=len(relations_to_insert)
                    )

                    for rel, public_id in zip(relations_to_insert, reserved_ids):
                        rel["public_id"] = public_id

                    # Bulk insert
                    self.dbm.insert_many(
                        collection=object_relation_collection,
                        db_name=self.db_name,
                        data=relations_to_insert,
                        skip_public=True
                    )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_mapper_relation(self, existing_type_ids: list[int]) -> dict[str, Any]:
        """
        TODO: document
        """
        mapper_relation: dict[str, Any] = {
            "relation_name": "DgObjectLinks",
            "relation_name_parent": "to secondary",
            "relation_icon_parent": "fa fa-cube",
            "relation_color_parent": "#e9ecef",
            "relation_name_child": "to primary",
            "relation_icon_child": "fa fa-cube",
            "relation_color_child": "#e9ecef",
            "parent_type_ids": existing_type_ids,
            "child_type_ids": existing_type_ids,
            "description": "",
            "sections": [],
            "fields": [],
        }

        return mapper_relation


    def get_object_relation_dict(
        self,
        parent_id: int,
        child_id: int,
        parent_type_id: int,
        child_type_id: int,
        relation_id: int,
    ) -> dict[str, Any]:
        """TODO: document"""
        return {
            "relation_id": relation_id,
            "relation_parent_id": parent_id,
            "relation_child_id": child_id,
            "relation_parent_type_id": parent_type_id,
            "relation_child_type_id": child_type_id,
            "author_id": 1,
            "field_values": [],
            "creation_time": datetime.now(timezone.utc)
        }
