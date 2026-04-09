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
TODO: document
"""
from logging import Logger, getLogger

from cmdb.manager import ObjectsManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.models.docapi_model.aggregated_fields import AggregatedFields
from cmdb.framework.rendering.cmdb_render import CmdbRender
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                RelationResult - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RelationResult:
    """
    Represents a set of objects reached via a relation.
    """
    def __init__(
        self,
        object_ids: list[int],
        object_cache: dict,
        type_cache: dict,
        object_relations: list[dict],        # scoped (for relation_fields)
        all_object_relations: list[dict],    # global (for traversal)
        request_user,
        objects_manager,
        template_type
    ) -> None:
        # LOGGER.debug("[RelationResult.__init__] object_ids=%s type=%s", object_ids, type(object_ids))
        self.object_ids = object_ids
        self.object_cache = object_cache
        self.type_cache = type_cache
        self.object_relations = object_relations              # scoped edges
        self.all_object_relations = all_object_relations      # global edges
        self.request_user = request_user
        self.objects_manager: ObjectsManager = objects_manager
        self.template_type = template_type


    def type(self, type_id: int) -> "RelationResult":
        """
        Filters objects by type but keeps scoped relations intact
        to preserve relation fields.
        """
        # LOGGER.debug(f"[RelationResult] TYPE => type_id: {type_id}")
        # LOGGER.debug("[RelationResult.type] object_cache keys=%s", list(self.object_cache.keys()))

        filtered_ids = []
        for oid in self.object_ids:
            obj = self.object_cache.get(oid)
            if obj and obj.get("type_id") == type_id:
                filtered_ids.append(oid)

        # LOGGER.debug("[RelationResult.type] input_ids=%s type_id=%s filtered=%s",
        #             self.object_ids, type_id, filtered_ids)

        return RelationResult(
            filtered_ids,
            self.object_cache,
            self.type_cache,
            self.object_relations,      # <-- keep scoped edges intact
            self.all_object_relations,  # global edges unchanged
            self.request_user,
            self.objects_manager,
            self.template_type
        )


    def relation(self, relation_id: int, side: str) -> "RelationResult":
        """TODO: document"""
        # LOGGER.debug(f"[RelationResult] RELATION => relation_id: {relation_id}, side: {side}")

        next_ids = []
        next_scoped_relations = []

        for rel in self.all_object_relations:
            if rel["relation_id"] != relation_id:
                continue

            if side == "parent" and rel["relation_child_id"] in self.object_ids:
                next_ids.append(rel["relation_parent_id"])
                next_scoped_relations.append(rel)

            elif side == "child" and rel["relation_parent_id"] in self.object_ids:
                next_ids.append(rel["relation_child_id"])
                next_scoped_relations.append(rel)

        # LOGGER.debug(
        #     "[RelationResult] NEXT STATE => from=%s to=%s next_scoped_edges=%s global_edges=%s",
        #     self.object_ids,
        #     next_ids,
        #     [(r["relation_parent_id"], r["relation_child_id"]) for r in next_scoped_relations],
        #     len(self.all_object_relations)
        # )

        # LOGGER.debug(
        #     "[RelationResult] NEXT SCOPED RELATIONS => %s",
        #     [
        #         {
        #             "parent": r["relation_parent_id"],
        #             "child": r["relation_child_id"],
        #             "fields": r.get("field_values")
        #         }
        #         for r in next_scoped_relations
        #     ]
        # )

        # Ensure all new objects are loaded into the object_cache
        # Collect IDs that are missing from cache
        missing_ids = [oid for oid in next_ids if oid not in self.object_cache]

        if missing_ids:
            # Single DB call to fetch all missing objects
            cursor = self.objects_manager.find(criteria={"public_id": {"$in": missing_ids}})
            for obj in cursor:
                self.object_cache[obj["public_id"]] = obj

        return RelationResult(
            next_ids,
            self.object_cache,
            self.type_cache,
            next_scoped_relations,      # scoped for relation_fields
            self.all_object_relations,  # global for further traversal
            self.request_user,
            self.objects_manager,
            self.template_type
    )


    # Terminals
    @property
    def public_id(self) -> list[int]:
        """
        TODO: document
        """
        return list(self.object_ids)


    @property
    def fields(self) -> AggregatedFields:
        """
        TODO: document
        """
        # LOGGER.debug("[RelationResult] FIELDS => fields")
        result = []

        for oid in self.object_ids:
            obj = self.object_cache.get(oid)
            if not obj:
                continue

            cmdb_object = CmdbObject.from_data(obj)
            obj_type = self.type_cache.get(cmdb_object.get_type_id())
            if not obj_type:
                continue

            render = CmdbRender(
                cmdb_object,
                CmdbType.from_data(obj_type),
                self.request_user,
                False,
            )

            result.append(
                ObjectTemplateData(
                    render.result(),
                    self.objects_manager,
                    self.request_user,
                    self.template_type
                ).get_template_data()["fields"]
            )

        return AggregatedFields(result)


    @property
    def relation_fields(self) -> AggregatedFields:
        """
        Returns relation fields for all edges in the scoped relations
        of this RelationResult, ignoring object_ids.
        """
        # LOGGER.debug("[RelationResult] RELATION FIELDS => object_ids=%s", self.object_ids)
        field_dicts = []

        # Iterate only scoped relations for this hop
        for rel in self.object_relations:
            fields = {}
            for fv in rel.get("field_values", []):
                name = fv.get("name")
                value = fv.get("value")
                if name:
                    fields[name] = value
            if fields:
                field_dicts.append(fields)
                # LOGGER.debug("[RelationResult] SCAN REL => parent=%s child=%s fields=%s",
                #             rel.get("relation_parent_id"),
                #             rel.get("relation_child_id"),
                #             fields)

        # LOGGER.debug("[RelationResult] DEBUG relation_fields: %s", field_dicts)
        return AggregatedFields(field_dicts)
