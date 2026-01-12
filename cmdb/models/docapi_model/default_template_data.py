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
from cmdb.manager import (
    ObjectsManager,
    TypesManager,
    ObjectRelationsManager,
    RelationsManager,
)

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
        self.objects_manager: ObjectsManager = ManagerProvider.get_manager(
            ManagerType.OBJECTS, request_user
        )
        self.types_manager: TypesManager = ManagerProvider.get_manager(
            ManagerType.TYPES, request_user
        )
        self.relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS, request_user
        )
        self.object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user
        )

        # --------------------------------------------------------------
        # Root object
        # --------------------------------------------------------------
        self.root_data = ObjectTemplateData(
            cmdb_render_object,
            self.objects_manager,
            self.request_user
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
                self.objects_manager,
                self.request_user
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
