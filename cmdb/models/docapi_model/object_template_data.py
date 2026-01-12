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
            request_user: CmdbUser
    ) -> None:
        """
        Initializes the ObjectTemplateData

        Args:
            cmdb_render_object (RenderResult): The RenderResult to extract data from
            objects_manager (ObjectsManager): The manager handling CmdbObject
        """
        self.objects_manager: ObjectsManager = objects_manager
        self.request_user: CmdbUser = request_user

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


    def extract_object_data(self, cmdb_render_object: RenderResult, depth: int) -> dict:
        """
        Recursively extracts object data from a RenderResult

        Args:
            cmdb_render_object (RenderResult): The RenderResult to extract data from
            depth (int): The recursion depth limit for resolving references

        Returns:
            dict: The extracted object data
        """
        # LOGGER.debug(f"cmdb_render_object.object_information: {cmdb_render_object.object_information}")
        data = {
            "id": cmdb_render_object.object_information.get("object_id"),
            "public_id": cmdb_render_object.object_information.get("object_id"),
            "fields": {}
        }

        for field in cmdb_render_object.fields:
            field_name = field.get("name")
            field_type = field.get("type")
            field_value = field.get("value")

            if not field_name:
                continue

            try:
                if field_name == "dg_location" and field_value:
                    try:
                        location = self.locations_manager.get_location(field_value)
                        data["fields"][field_name] = location.get("name")
                    except Exception as err:
                        LOGGER.error(
                            "Failed to resolve location %s for field dg_location: %s",
                            field_value,
                            err,
                        )
                        data["fields"][field_name] = None
                elif field_type in ("ref", "location") and field_value and depth > 0:
                    # resolve type
                    related_object = self.objects_manager.get_object(field_value)
                    related_object = CmdbObject.from_data(related_object)
                    object_type = self.objects_manager.get_object_type(related_object.get_type_id())

                    related_render = CmdbRender(related_object, object_type, None, False)

                    data["fields"][field_name] = self.extract_object_data(related_render.result(), depth - 1)
                elif field_type == 'ref-section-field':
                    data["fields"][field_name] = {
                        "fields": {ref["name"]: ref["value"] for ref in field.get("references", {}).get("fields", [])}
                    }
                else:
                    data["fields"][field_name] = field_value
            except ObjectsManagerGetError:
                LOGGER.error("Failed to retrieve object for field '%s'. Skipping.", field_name)
            except Exception as err:
                LOGGER.error("Exception processing field '%s': %s", field_name, err)

        return data
