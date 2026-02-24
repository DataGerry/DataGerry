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
from typing import Any

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, LocationsManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.framework.rendering.cmdb_render import CmdbRender
from cmdb.framework.rendering.render_result import RenderResult

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ObjectTemplateData - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectTemplateData:
    """
    Prepares and retrieves template data for a given RenderResult
    """
    def __init__(
        self,
        cmdb_render_object: RenderResult,
        objects_manager: ObjectsManager,
        request_user: CmdbUser,
        template_type: str
    ) -> None:
        """
        Initializes the ObjectTemplateData

        Args:
            cmdb_render_object (RenderResult): The RenderResult to extract data from
            objects_manager (ObjectsManager): The manager handling CmdbObject
        """
        self.objects_manager: ObjectsManager = objects_manager
        self.request_user: CmdbUser = request_user
        self.template_type = template_type

        self.modern_templates = self.template_type == "DEFAULT"

        self.locations_manager: LocationsManager = ManagerProvider.get_manager(
            ManagerType.LOCATIONS, request_user
        )

        self.template_data = self.extract_object_data(cmdb_render_object, 3)


    def get_template_data(self) -> dict:
        """
        Retrieves the processed template data

        Returns:
            dict: The structured template data extracted from the RenderResult
        """
        return self.template_data


    def _resolve_reference(self, public_id, depth):
        try:
            related_object: CmdbObject | None = self.objects_manager.get_object(public_id, as_dict=False)
            object_type = self.objects_manager.get_object_type(
                related_object.get_type_id()
            )

            related_render = CmdbRender(
                related_object,
                object_type,
                None,
                False
            )

            return self.extract_object_data(
                related_render.result(),
                depth - 1
            )
        except Exception:
            return None


    def _resolve_field(self, name, ftype, value, references, depth):
        # Location
        if name == "dg_location" and value:
            try:
                location = self.locations_manager.get_location(value)
                return location.get("name")
            except Exception:
                return ""

        if name == "dg_location" and not value:
            return ""

        # OBJECT templates (legacy)
        if not self.modern_templates:
            if ftype in ("ref", "location"):
                if value and depth > 0:
                    return self._resolve_reference(value, depth)
                return value
            if ftype == "ref-section-field":
                return {
                    "fields": {
                        ref["name"]: ref.get("value", "")
                        for ref in (references or {}).get("fields", [])
                    }
                }
            return value

        # DEFAULT templates (modern)
        if ftype in ("ref", "location") and value and depth > 0:
            return self._resolve_reference(value, depth)

        if ftype == "ref-section-field":
            section_fields = {}
            for ref in (references or {}).get("fields", []):
                section_fields[ref["name"]] = self._resolve_field(
                    name=ref.get("name"),
                    ftype=ref.get("type"),
                    value=ref.get("value", ""),
                    references=ref.get("references"),
                    depth=depth,
                )
            return {"fields": section_fields}

        return value


    def extract_object_data(self, cmdb_render_object: RenderResult, depth: int) -> dict:
        """
        Recursively extracts object data from a RenderResult

        Args:
            cmdb_render_object (RenderResult): The RenderResult to extract data from
            depth (int): The recursion depth limit for resolving references

        Returns:
            dict: The extracted object data
        """
        data: dict[str, Any] = {
            "id": cmdb_render_object.object_information.get("object_id"),
            "public_id": cmdb_render_object.object_information.get("object_id"),
            "fields": {}
        }

        for field in cmdb_render_object.fields:
            field_name = field.get("name")
            if not field_name:
                continue

            try:
                data["fields"][field_name] = self._resolve_field(
                    name=field_name,
                    ftype=field.get("type"),
                    value=field.get("value"),
                    references=field.get("references"),
                    depth=depth,
                )
            except ObjectsManagerGetError:
                LOGGER.error("Failed to retrieve object for field '%s'. Skipping.", field_name)
            except Exception as err:
                LOGGER.error("Exception processing field '%s': %s", field_name, err)

        # Multi Data Sections
        mds_result = {}

        for section in cmdb_render_object.multi_data_sections or []:
            section_id = section.get("section_id")
            if not section_id:
                continue

            aggregated: dict[str, list] = {}

            for entry in section.get("values", []):
                for field in entry.get("data", []):
                    name = field.get("name")
                    value = field.get("value")

                    if name is None:
                        continue

                    aggregated.setdefault(name, []).append(value)

            # convert lists to comma-separated strings
            mds_result[section_id] = {
                field_name: ", ".join(
                    "" if v is None else str(v) for v in values
                )
                for field_name, values in aggregated.items()
            }

        if mds_result:
            data["mds"] = mds_result

        return data
