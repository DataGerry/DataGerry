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
Implementation of ObjectTemplateData
"""
from logging import Logger, getLogger
import re
from typing import Any

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
# from cmdb.manager import ObjectsManager, TypesManager, ObjectRelationsManager, RelationsManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
# from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.type_model import CmdbType
from cmdb.framework.rendering.cmdb_render import CmdbRender
# from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.docapi_model.relation_result import RelationResult


# from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

EXTERNAL_OBJECT_REGEX = re.compile(r"\{\{\s*object\((\d+)\)")
REPORT_REGEX = re.compile(r"\{\{\s*report\((\d+)\)\s*\}\}")

RELATION_PLACEHOLDER_REGEX = re.compile(
    r"""
    root
    (?:
        \.relation\(\s*\d+\s*,\s*(?:parent|child)\s*\)
        (?:\.type\(\s*\d+\s*\))?
    )+
    (?:
        \.(?:fields|relation_field)\[['"].+?['"]\]
        |\.public_id
    )?
    """,
    re.VERBOSE,
)

RELATION_STEP_REGEX = re.compile(
    r"""
    \.relation\(
        \s*(\d+)\s*,\s*(parent|child)\s*
    \)
    (?:\.type\(\s*(\d+)\s*\))?
    """,
    re.VERBOSE,
)

TERMINAL_REGEX = re.compile(
    r"""
    \.(fields|relation_field)\[['"](.+?)['"]\]
    |\.public_id
    """,
    re.VERBOSE,
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              DefaultTemplateData - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultTemplateData:
    """
    FINAL stable DEFAULT template data builder.
    """

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(
        self,
        cmdb_render_object,
        template_string: str,
        request_user,
    ) -> None:
        self.template_string = template_string
        self.request_user = request_user

        # --------------------------------------------------------------
        # Managers
        # --------------------------------------------------------------
        self.objects_manager = ManagerProvider.get_manager(
            ManagerType.OBJECTS, request_user
        )
        self.types_manager = ManagerProvider.get_manager(
            ManagerType.TYPES, request_user
        )
        self.relations_manager = ManagerProvider.get_manager(
            ManagerType.RELATIONS, request_user
        )
        self.object_relations_manager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user
        )

        # --------------------------------------------------------------
        # Root object
        # --------------------------------------------------------------
        self.root_data = ObjectTemplateData(
            cmdb_render_object,
            self.objects_manager
        ).get_template_data()

        self.root_object_id = self.root_data["public_id"]

        # --------------------------------------------------------------
        # Parse template once
        # --------------------------------------------------------------
        self.external_object_ids = {
            int(m) for m in EXTERNAL_OBJECT_REGEX.findall(template_string)
        }

        self.report_ids = {
            int(m) for m in REPORT_REGEX.findall(template_string)
        }

        self.relation_placeholders = [
            m.group()
            for m in RELATION_PLACEHOLDER_REGEX.finditer(template_string)
        ]

        # --------------------------------------------------------------
        # Caches
        # --------------------------------------------------------------
        self.object_cache: dict[int, dict] = {}
        self.type_cache: dict[int, dict] = {}
        self.relation_cache: dict[int, dict] = {}
        self.object_relations: dict[dict] = []

        # --------------------------------------------------------------
        # Fetch objects
        # --------------------------------------------------------------
        object_ids = set(self.external_object_ids)
        object_ids.add(self.root_object_id)

        if object_ids:
            cursor = self.objects_manager.find(
                criteria={"public_id": {"$in": list(object_ids)}}
            )
            for obj in cursor:
                self.object_cache[obj["public_id"]] = obj

        # --------------------------------------------------------------
        # Fetch types
        # --------------------------------------------------------------
        type_ids = {
            obj["type_id"]
            for obj in self.object_cache.values()
            if obj.get("type_id")
        }

        if type_ids:
            cursor = self.types_manager.find(
                criteria={"public_id": {"$in": list(type_ids)}}
            )
            for t in cursor:
                self.type_cache[t["public_id"]] = t

        # --------------------------------------------------------------
        # Fetch relations + object relations
        # --------------------------------------------------------------
        relation_ids = set()

        for placeholder in self.relation_placeholders:
            for rel_id, _, _ in RELATION_STEP_REGEX.findall(placeholder):
                relation_ids.add(int(rel_id))

        if relation_ids:
            cursor = self.relations_manager.find(
                criteria={"public_id": {"$in": list(relation_ids)}}
            )
            for r in cursor:
                self.relation_cache[r["public_id"]] = r

            cursor = self.object_relations_manager.find(
                criteria={"relation_id": {"$in": list(relation_ids)}}
            )
            self.object_relations = list(cursor)

        # --------------------------------------------------------------
        # Final template data
        # --------------------------------------------------------------
        self.template_data = {
            "root": self._root_accessor(),
            "object": self._object_accessor(),
            "report": self._report_accessor(),
        }

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get_template_data(self) -> dict[str, Any]:
        """TODO: document"""
        return self.template_data

    # ------------------------------------------------------------------
    # Root accessor (relations start here)
    # ------------------------------------------------------------------

    def _root_accessor(self):
        root = dict(self.root_data)
        root["relation"] = self._relation_accessor(self.root_object_id)
        return root

    # ------------------------------------------------------------------
    # Relation traversal engine
    # ------------------------------------------------------------------

    def _relation_accessor(self, start_object_id: int):
        def _relation_fn(relation_id: int, side: str):
            return self._relation_traversal(
                start_object_id,
                relation_id,
                side
            )
        return _relation_fn

    def _relation_traversal(
        self,
        start_object_id: int,
        relation_id: int,
        side: str,
    ):
        matches = []

        for rel in self.object_relations:
            if rel["relation_id"] != relation_id:
                continue

            if side == "parent" and rel["child_id"] == start_object_id:
                matches.append(rel["parent_id"])
            elif side == "child" and rel["parent_id"] == start_object_id:
                matches.append(rel["child_id"])

        return RelationResult(
            matches,
            self.object_cache,
            self.type_cache,
            self.object_relations,
            self.request_user,
            self.objects_manager,
        )

    # ------------------------------------------------------------------
    # External object accessor
    # ------------------------------------------------------------------

    def _object_accessor(self):
        def _object_fn(public_id: int):
            obj = self.object_cache.get(public_id)
            if not obj:
                return None

            cmdb_object = CmdbObject.from_data(obj)
            obj_type = self.type_cache.get(cmdb_object.get_type_id())
            if not obj_type:
                return None

            render = CmdbRender(
                cmdb_object,
                CmdbType.from_data(obj_type),
                self.request_user,
                False,
            )

            return ObjectTemplateData(
                render.result(),
                self.objects_manager
            ).get_template_data()

        return _object_fn

    # ------------------------------------------------------------------
    # Report accessor (stub)
    # ------------------------------------------------------------------

    def _report_accessor(self):
        def _report_fn(public_id: int):
            if public_id not in self.report_ids:
                return None
            return {"public_id": public_id}
        return _report_fn
# class DefaultTemplateData:
#     """
#     Prepares and retrieves template data for DEFAULT templates,
#     supporting explicit root object and extensions for external objects, reports, and relations.
#     """
#     def __init__(
#             self,
#             cmdb_render_object: RenderResult,
#             template_string: str,
#             request_user: CmdbUser
#         ) -> None:
#         self.template_string: str = template_string
#         self.request_user: CmdbUser = request_user

#         self.objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, self.request_user)
#         self.types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, self.request_user)
#         self.object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
#             ManagerType.OBJECT_RELATIONS,
#             self.request_user
#         )
#         self.relations_manager: RelationsManager = ManagerProvider.get_manager(
#             ManagerType.RELATIONS,
#             self.request_user
#         )

#         # ------------------------------------------------------------
#         # Root object (already rendered)
#         # ------------------------------------------------------------
#         self._root_data = ObjectTemplateData(
#             cmdb_render_object,
#             self.objects_manager
#         ).get_template_data()

#         self._root_object_id: int = cmdb_render_object.object_information.get("object_id")
#         self._root_type_id: int | None = cmdb_render_object.type_information.get("type_id")

#         # ------------------------------------------------------------
#         # ID collections (simple placeholders)
#         # ------------------------------------------------------------
#         self._external_object_ids: set[int] = {
#             int(m) for m in EXTERNAL_OBJECT_REGEX.findall(template_string)
#         }

#         self._report_ids: set[int] = {
#             int(m) for m in REPORT_REGEX.findall(template_string)
#         }

#         # ------------------------------------------------------------
#         # Relation placeholders (structured, ordered)
#         # ------------------------------------------------------------
#         self._relation_placeholders: list[dict] = []
#         self._collect_relation_placeholders(template_string)

#         # ------------------------------------------------------------
#         # Traversal preparation caches
#         # ------------------------------------------------------------
#         # These caches allow relation traversal without re-querying
#         self._object_cache: dict[int, dict] = {}
#         self._type_cache: dict[int, dict] = {}
#         self._relation_cache: dict[int, dict] = {}
#         self._object_relation_cache: dict[tuple[int, int, str], list[dict]] = {}

#         # ------------------------------------------------------------
#         # Collect type IDs (root + external objects)
#         # ------------------------------------------------------------
#         self._type_ids: set[int] = set()

#         if self._root_type_id:
#             self._type_ids.add(self._root_type_id)

#         # ------------------------------------------------------------
#         # Fetch external objects (cached)
#         # ------------------------------------------------------------
#         if self._external_object_ids:
#             cursor = self.objects_manager.find(
#                 criteria={"public_id": {"$in": list(self._external_object_ids)}}
#             )
#             for obj in cursor:
#                 public_id = obj["public_id"]
#                 self._object_cache[public_id] = obj

#                 if obj.get("type_id"):
#                     self._type_ids.add(obj["type_id"])

#         # ------------------------------------------------------------
#         # Pre-collect type IDs from relation placeholders
#         # ------------------------------------------------------------
#         for placeholder in self._relation_placeholders:
#             for step in placeholder["steps"]:
#                 if step.get("type_id"):
#                     self._type_ids.add(step["type_id"])

#         # ------------------------------------------------------------
#         # Fetch and cache types
#         # ------------------------------------------------------------
#         if self._type_ids:
#             cursor = self.types_manager.find(
#                 criteria={"public_id": {"$in": list(self._type_ids)}}
#             )
#             self._type_cache = {t["public_id"]: t for t in cursor}

#         # ------------------------------------------------------------
#         # Final template data exposed to Jinja
#         # ------------------------------------------------------------
#         self.template_data = {
#             "root": self._root_data,
#             "object": self._object_accessor(),
#             "report": self._report_accessor(),
#             "relation": self._relation_accessor(),  # traversal comes next
#         }


#     def get_template_data(self) -> dict[str, Any]:
#         """
#         Provides the processed template data

#         Returns:
#             dict[str, Any]: A dictionary with the values for the template building
#         """
#         return self.template_data


#     def _get_object_relations(
#         self,
#         object_id: int,
#         relation_id: int,
#         role: str
#     ) -> list[dict]:
#         cache_key = (object_id, relation_id, role)

#         if cache_key in self._object_relation_cache:
#             return self._object_relation_cache[cache_key]

#         criteria = {
#             "relation_id": relation_id,
#             f"relation_{role}_id": object_id,
#         }

#         relations = list(
#             self.object_relations_manager.find(criteria=criteria)
#         )

#         self._object_relation_cache[cache_key] = relations
#         return relations


#     def _get_object(self, public_id: int) -> dict | None:
#         if public_id in self._object_cache:
#             return self._object_cache[public_id]

#         obj = self.objects_manager.get_object(public_id)
#         self._object_cache[public_id] = obj
#         return obj


#     def _collect_relation_placeholders(self, template_string: str) -> None:
#         """
#         Parses all relation placeholders into structured traversal steps.
#         """
#         for match in RELATION_PLACEHOLDER_REGEX.finditer(template_string):
#             steps = []

#             step_matches = RELATION_STEP_REGEX.findall(match.group(0))
#             for relation_id, side, type_id in step_matches:
#                 steps.append({
#                     "relation_id": int(relation_id),
#                     "side": side,
#                     "type_id": int(type_id) if type_id else None,
#                 })

#             terminal = self._parse_relation_terminal(match.group(0))

#             self._relation_placeholders.append({
#                 "raw": match.group(0),
#                 "steps": steps,
#                 "terminal": terminal,
#             })


#     def _parse_relation_placeholder(self, placeholder: str) -> list[dict]:
#         """
#         Parses a single relation placeholder into a list of steps.

#         Each step contains:
#             relation_id, side, optional type_id
#         The last step may contain terminal_type and terminal_name
#         """
#         steps = []
#         remaining = placeholder.strip()

#         # Remove leading 'root.'
#         if remaining.startswith("root."):
#             remaining = remaining[5:]

#         # Parse relation steps
#         while True:
#             rel_match = RELATION_STEP_REGEX.match(remaining)
#             if not rel_match:
#                 break

#             relation_id = int(rel_match.group(1))
#             side = rel_match.group(2)
#             type_id = int(rel_match.group(3)) if rel_match.group(3) else None

#             step = {"relation_id": relation_id, "side": side, "type_id": type_id}
#             steps.append(step)

#             # Move past this relation
#             remaining = remaining[rel_match.end():]

#         # Parse terminal
#         terminal_match = TERMINAL_REGEX.match(remaining)
#         if terminal_match:
#             if terminal_match.group(1):  # field or relation_field
#                 steps[-1]["terminal_type"] = terminal_match.group(1)
#                 steps[-1]["terminal_name"] = terminal_match.group(2)
#             else:  # public_id
#                 steps[-1]["terminal_type"] = "public_id"

#         return steps


#     # ------------------------------------------------------------------ #
#     # Jinja accessors
#     # ------------------------------------------------------------------ #

#     def _object_accessor(self):
#         def _object_fn(public_id: int):
#             obj_data = self._external_objects.get(public_id)
#             if not obj_data:
#                 return None

#             try:
#                 cmdb_object = CmdbObject.from_data(obj_data)
#                 object_type = self._type_cache.get(cmdb_object.get_type_id())

#                 if not object_type:
#                     return None

#                 object_type = CmdbType.from_data(object_type)
#                 render = CmdbRender(cmdb_object, object_type, self.request_user, False)
#                 return ObjectTemplateData(
#                     render.result(),
#                     self.objects_manager
#                 ).get_template_data()

#             except ObjectsManagerGetError:
#                 LOGGER.error("Failed to resolve external object %s", public_id)
#                 return None

#         return _object_fn


#     def _report_accessor(self):
#         def _report_fn(public_id: int):
#             if public_id not in self._report_ids:
#                 return None
#             # backend resolves report later
#             return {"public_id": public_id}

#         return _report_fn


#     def _relation_accessor(self):
#         """
#         Provides a Jinja-accessible function to resolve relation placeholders dynamically.

#         Usage in Jinja:
#             {{ relation(public_id_of_placeholder) }}
#         """

#         def _relation_fn(placeholder_id: int):
#             """
#             Resolves the relation placeholder identified by its index in _relation_placeholders.
#             """
#             if placeholder_id >= len(self._relation_placeholders):
#                 return None

#             placeholder = self._relation_placeholders[placeholder_id]
#             chain = placeholder["relations"]
#             terminal_type = placeholder["terminal_type"]
#             terminal_value = placeholder["terminal_value"]

#             # Start from root object
#             current_objects = [self._root_data]

#             # Traverse each relation in the chain
#             for step in chain:
#                 next_objects = []
#                 relation_id = step["relation_id"]
#                 role = step["role"]
#                 type_id = step.get("type_id")

#                 for obj in current_objects:
#                     # Find all ObjectRelations for this obj matching relation_id and role
#                     obj_relations = self.object_relations_manager.find(
#                         criteria={
#                             "relation_id": relation_id,
#                             "relation_parent_id" if role == "parent" else "relation_child_id": obj["public_id"]
#                         }
#                     )

#                     for obj_rel in obj_relations:
#                         # Identify the connected object based on role
#                         if role == "parent":
#                             child_obj_id = obj_rel["relation_child_id"]
#                             child_obj = self.objects_manager.get_object(child_obj_id)
#                             if type_id and child_obj["type_id"] != type_id:
#                                 continue
#                             next_objects.append(child_obj)
#                         else:
#                             parent_obj_id = obj_rel["relation_parent_id"]
#                             parent_obj = self.objects_manager.get_object(parent_obj_id)
#                             if type_id and parent_obj["type_id"] != type_id:
#                                 continue
#                             next_objects.append(parent_obj)

#                 current_objects = next_objects

#             # After traversing the chain, extract the terminal
#             results = []
#             for obj in current_objects:
#                 if terminal_type == "field":
#                     results.append(obj["fields"].get(terminal_value))
#                 elif terminal_type == "relation_field":
#                     # relation fields stored in obj_rel["field_values"]
#                     for obj_rel in obj_relations:
#                         value = next(
#                             (fv["value"] for fv in obj_rel.get("field_values", []) if fv["name"] == terminal_value),
#                             None
#                         )
#                         if value is not None:
#                             results.append(value)
#                 elif terminal_type == "public_id":
#                     results.append(obj["public_id"])

#             return results if len(results) > 1 else results[0] if results else None

#         return _relation_fn
