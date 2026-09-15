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
This module contains the RelationResult class used to traverse object relations inside DocAPI templates.
"""
from logging import Logger, getLogger

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.models.docapi_model.aggregated_fields import AggregatedFields
from cmdb.models.docapi_model.docapi_cache_helper import cache_objects_and_types
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.relation_side_enum import RelationSide
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                RelationResult - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RelationResult:
    """
    Represents a set of objects reached via a relation hop.

    Instances form a fluent, immutable traversal API exposed to DocAPI templates: `type()` and
    `relation()` each return a new RelationResult, while the `public_id`, `fields` and
    `relation_fields` properties are the terminals that materialise data for the template.
    """
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(
        self,
        object_ids: list[int],
        object_cache: dict[int, dict],
        type_cache: dict[int, dict],
        object_relations: list[dict],        # scoped (for relation_fields)
        all_object_relations: list[dict],    # global (for traversal)
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        template_type: DocapiTemplateType,
    ) -> None:
        self.object_ids = object_ids
        self.object_cache = object_cache
        self.type_cache = type_cache
        self.object_relations = object_relations              # scoped edges
        self.all_object_relations = all_object_relations      # global edges
        self.request_user = request_user
        self.objects_manager: ObjectsManager = objects_manager
        self.types_manager: TypesManager = types_manager
        self.template_type = template_type


    def type(self, type_id: int) -> "RelationResult":
        """
        Filters the current objects down to those of the given type

        The scoped relations are kept intact so `relation_fields` still reflects the edges that led
        here, even after narrowing the objects by type.

        Args:
            type_id (int): The public_id of the type to keep

        Returns:
            RelationResult: A new result containing only the objects of `type_id`
        """
        filtered_ids = [
            oid for oid in self.object_ids
            if (obj := self.object_cache.get(oid)) and obj.get("type_id") == type_id
        ]

        return RelationResult(
            filtered_ids,
            self.object_cache,
            self.type_cache,
            self.object_relations,      # keep scoped edges intact
            self.all_object_relations,  # global edges unchanged
            self.request_user,
            self.objects_manager,
            self.types_manager,
            self.template_type,
        )


    def relation(self, relation_id: int, side: str) -> "RelationResult":
        """
        Traverses one relation hop from the current objects

        Following `relation_id` towards `side`, this collects the objects on the other end of every
        matching edge and lazily loads them (and their types) into the shared caches so downstream
        terminals such as `fields` can render them.

        Args:
            relation_id (int): The public_id of the relation to follow
            side (str): The side to traverse towards ('parent' or 'child', see RelationSide)

        Returns:
            RelationResult: A new result for the objects reached by this hop
        """
        next_ids = []
        next_scoped_relations = []

        for rel in self.all_object_relations:
            if rel["relation_id"] != relation_id:
                continue

            if side == RelationSide.PARENT and rel["relation_child_id"] in self.object_ids:
                next_ids.append(rel["relation_parent_id"])
                next_scoped_relations.append(rel)
            elif side == RelationSide.CHILD and rel["relation_parent_id"] in self.object_ids:
                next_ids.append(rel["relation_child_id"])
                next_scoped_relations.append(rel)

        # Load any newly reached objects (and their types) into the shared caches
        cache_objects_and_types(
            next_ids,
            self.object_cache,
            self.type_cache,
            self.objects_manager,
            self.types_manager,
        )

        return RelationResult(
            next_ids,
            self.object_cache,
            self.type_cache,
            next_scoped_relations,      # scoped for relation_fields
            self.all_object_relations,  # global for further traversal
            self.request_user,
            self.objects_manager,
            self.types_manager,
            self.template_type,
        )

    # Terminals
    @property
    def public_id(self) -> list[int]:
        """
        Returns the public_ids of the objects reached by this result

        Returns:
            list[int]: A copy of the current object public_ids
        """
        return list(self.object_ids)


    @property
    def fields(self) -> AggregatedFields:
        """
        Renders the current objects and aggregates their template fields

        Objects whose type is not available in the cache are skipped. All renderable objects are
        rendered in a single CmdbMultiRender pass (one bulk lookup) rather than one render per object.

        Returns:
            AggregatedFields: The per-object field dicts, aggregated for template access
        """
        cmdb_objects = []

        for oid in self.object_ids:
            obj = self.object_cache.get(oid)
            if not obj:
                continue

            cmdb_object = CmdbObject.from_data(obj)
            if not self.type_cache.get(cmdb_object.get_type_id()):
                continue

            cmdb_objects.append(cmdb_object)

        if not cmdb_objects:
            return AggregatedFields([])

        renders: list[RenderResult] = CmdbMultiRender(cmdb_objects, self.request_user).result()

        result = [
            ObjectTemplateData(
                render,
                self.objects_manager,
                self.request_user,
                self.template_type,
            ).get_template_data()["fields"]
            for render in renders
        ]

        return AggregatedFields(result)


    @property
    def relation_fields(self) -> AggregatedFields:
        """
        Aggregates the field values stored on the scoped relations of this hop

        Reads the `field_values` of every scoped edge (ignoring `object_ids`) so a template can
        access the values carried by the relation itself rather than by the related objects.

        Returns:
            AggregatedFields: The per-edge relation field dicts, aggregated for template access
        """
        field_dicts = []

        for rel in self.object_relations:
            fields = {}
            for fv in rel.get("field_values", []):
                name = fv.get("name")
                if name:
                    fields[name] = fv.get("value")
            if fields:
                field_dicts.append(fields)

        return AggregatedFields(field_dicts)
