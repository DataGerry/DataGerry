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
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.framework.rendering.cmdb_render import CmdbRender
from cmdb.framework.rendering.render_result import RenderResult


from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

EXTERNAL_OBJECT_REGEX = re.compile(r"object\(\s*(\d+)\s*\)")

# -------------------------------------------------------------------------------------------------------------------- #
#                                              DefaultTemplateData - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultTemplateData(ObjectTemplateData):
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
        # Call base class to extract root object data
        super().__init__(cmdb_render_object, objects_manager)

        self.objects_manager: ObjectsManager = objects_manager
        self.types_manager: TypesManager = types_manager

        # Internal caches
        self._external_object_ids: Set[int] = set()
        self._type_ids: Set[int] = set()

        # ---- ROOT DATA -----------------------------------------------------
        # Base class already extracted root object data into self.template_data
        root_data = self.template_data

        root_type_id = cmdb_render_object.object_information.get("type_id")
        if root_type_id:
            self._type_ids.add(root_type_id)

        # Wrap root explicitly
        self.template_data = {
            "root": root_data,
            "objects": {},
            "reports": {},
        }

        # ---- EXTERNAL OBJECTS ---------------------------------------------
        self._collect_external_object_ids(template_string)
        self._collect_type_ids_from_objects()
        self._type_cache = self._fetch_types()
        self._populate_external_objects()

    # ---------------------------------------------------------------------
    # External object handling
    # ---------------------------------------------------------------------

    def _collect_external_object_ids(self, template_string: str) -> None:
        """
        Scans the template for external object placeholders
        and populates `_external_object_ids`.
        """
        matches = EXTERNAL_OBJECT_REGEX.findall(template_string)
        self._external_object_ids = {int(public_id) for public_id in matches}


    def _collect_type_ids_from_objects(self) -> None:
        """
        Collects type_ids from all external objects so they can be fetched in bulk.
        """
        if not self._external_object_ids:
            return

        cursor = self.objects_manager.find(
            criteria={"public_id": {"$in": list(self._external_object_ids)}}
        )

        for obj in cursor:
            type_id = obj.get("type_id")
            if type_id:
                self._type_ids.add(type_id)


    def _fetch_types(self) -> Dict[int, dict]:
        """
        Fetch all required types in one call and cache them.
        """
        if not self._type_ids:
            return {}

        cursor = self.types_manager.find(
            criteria={"public_id": {"$in": list(self._type_ids)}}
        )

        return {t["public_id"]: t for t in cursor}


    def _populate_external_objects(self) -> None:
        """
        Resolves all external objects and renders them like the root object.
        """
        if not self._external_object_ids:
            return

        cursor = self.objects_manager.find(
            criteria={"public_id": {"$in": list(self._external_object_ids)}}
        )

        for obj_data in cursor:
            try:
                cmdb_object = CmdbObject.from_data(obj_data)
                type_id = cmdb_object.get_type_id()
                object_type = self._type_cache.get(type_id)

                if not object_type:
                    LOGGER.warning(
                        "Type %s not found for object %s",
                        type_id,
                        cmdb_object.get_public_id(),
                    )
                    continue

                render = CmdbRender(cmdb_object, object_type, None, False)
                rendered_data = self.extract_object_data(render.result(), depth=3)

                self.template_data["objects"][cmdb_object.get_public_id()] = rendered_data

            except ObjectsManagerGetError:
                LOGGER.error(
                    "Failed to retrieve external object %s", obj_data.get("public_id")
                )
            except Exception as err:
                LOGGER.exception(err)
