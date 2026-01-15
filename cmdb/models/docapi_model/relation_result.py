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
        object_relations: list[dict],
        request_user,
        objects_manager,
    ):
        self.object_ids = object_ids
        self.object_cache = object_cache
        self.type_cache = type_cache
        self.object_relations = object_relations
        self.request_user = request_user
        self.objects_manager = objects_manager

    def type(self, type_id: int):
        """TODO: document"""
        filtered = []
        for oid in self.object_ids:
            obj = self.object_cache.get(oid)
            if obj and obj.get("type_id") == type_id:
                filtered.append(oid)

        return RelationResult(
            filtered,
            self.object_cache,
            self.type_cache,
            self.object_relations,
            self.request_user,
            self.objects_manager,
        )

    def relation(self, relation_id: int, side: str):
        """TODO: document"""
        LOGGER.debug("[RelationResult->relation] called")
        next_ids = []

        for rel in self.object_relations:
            if rel["relation_id"] != relation_id:
                continue

            if side == "parent" and rel["relation_child_id"] in self.object_ids:
                next_ids.append(rel["relation_parent_id"])
            elif side == "child" and rel["relation_parent_id"] in self.object_ids:
                next_ids.append(rel["relation_child_id"])

        return RelationResult(
            next_ids,
            self.object_cache,
            self.type_cache,
            self.object_relations,
            self.request_user,
            self.objects_manager,
        )

    # -----------------------------
    # Terminals
    # -----------------------------

    @property
    def public_id(self):
        """TODO: document"""
        return [oid for oid in self.object_ids]

    @property
    def fields(self):
        """TODO: document"""
        result = []

        for oid in self.object_ids:
            obj = self.object_cache.get(oid)
            if not obj:
                LOGGER.debug(">>>>[No obj]<<<<")
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
                    self.request_user
                ).get_template_data()["fields"]
            )

        return AggregatedFields(result)
