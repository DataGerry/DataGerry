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
from typing import Dict, Set

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.framework.rendering.cmdb_render import CmdbRender
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

EXTERNAL_OBJECT_REGEX = re.compile(r"\{\{\s*object\((\d+)\)")
REPORT_REGEX = re.compile(r"\{\{\s*report\((\d+)\)\s*\}\}")
# -------------------------------------------------------------------------------------------------------------------- #
#                                              DefaultTemplateData - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultTemplateData:
    """
    Prepares and retrieves template data for DEFAULT templates,
    supporting explicit root object and future extensions for external objects, reports, and relations.
    """
    def __init__(
            self,
            cmdb_render_object: RenderResult,
            objects_manager: ObjectsManager,
            types_manager: TypesManager,
            template_string: str
        ) -> None:
        self.objects_manager = objects_manager
        self.types_manager = types_manager
        self.template_string = template_string

        # ------------------------------------------------------------------
        # Collect IDs from template
        # ------------------------------------------------------------------
        self._external_object_ids: Set[int] = {
            int(m) for m in EXTERNAL_OBJECT_REGEX.findall(template_string)
        }

        self._report_ids: Set[int] = {
            int(m) for m in REPORT_REGEX.findall(template_string)
        }

        # ------------------------------------------------------------------
        # Root object (already rendered)
        # ------------------------------------------------------------------
        self._root_data = ObjectTemplateData(
            cmdb_render_object,
            self.objects_manager
        ).get_template_data()

        root_type_id = cmdb_render_object.type_information.get("type_id")
        # ------------------------------------------------------------------
        # Fetch external objects
        # ------------------------------------------------------------------
        self._external_objects: Dict[int, dict] = {}
        self._type_ids: Set[int] = set()

        if root_type_id:
            self._type_ids.add(root_type_id)

        if self._external_object_ids:
            cursor = self.objects_manager.find(
                criteria={"public_id": {"$in": list(self._external_object_ids)}}
            )
            for obj in cursor:
                self._external_objects[obj["public_id"]] = obj
                if obj.get("type_id"):
                    self._type_ids.add(obj["type_id"])

        # ------------------------------------------------------------------
        # Fetch types (cached)
        # ------------------------------------------------------------------
        self._type_cache = {}

        if self._type_ids:
            cursor = self.types_manager.find(
                criteria={"public_id": {"$in": list(self._type_ids)}}
            )

            self._type_cache = {t["public_id"]: t for t in cursor}
        # ------------------------------------------------------------------
        # Build final template data
        # ------------------------------------------------------------------
        self.template_data = {
            "root": self._root_data,
            "object": self._object_accessor(),
            "report": self._report_accessor(),
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_template_data(self) -> dict:
        return self.template_data

    # ------------------------------------------------------------------ #
    # Jinja accessors
    # ------------------------------------------------------------------ #

    def _object_accessor(self):
        def _object_fn(public_id: int):
            obj_data = self._external_objects.get(public_id)
            if not obj_data:
                return None

            try:
                cmdb_object = CmdbObject.from_data(obj_data)
                object_type = self._type_cache.get(cmdb_object.get_type_id())

                if not object_type:
                    return None

                object_type = CmdbType.from_data(object_type)
                render = CmdbRender(cmdb_object, object_type, None, False)
                return ObjectTemplateData(
                    render.result(),
                    self.objects_manager
                ).get_template_data()

            except ObjectsManagerGetError:
                LOGGER.error("Failed to resolve external object %s", public_id)
                return None

        return _object_fn

    def _report_accessor(self):
        def _report_fn(public_id: int):
            if public_id not in self._report_ids:
                return None
            # backend resolves report later
            return {"public_id": public_id}

        return _report_fn
