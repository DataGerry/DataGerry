# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of OpenCelium TemplateManager
"""
import json
from logging import Logger, getLogger
from typing import Any, Optional

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.template import OcTemplateGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

TEMPLATE_URL: str = "/template"
ALL_TEMPLATES_URL: str = f"{TEMPLATE_URL}/all"

# -------------------------------------------------------------------------------------------------------------------- #
#                                               OcTemplateManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class OcTemplateManager(OcBaseManager):
    """
    Manages Templates of OpenCelium
    """

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_template_by_id(self, template_id: int) -> dict[str, Any]:
        """
        Retrieves the OcTemplate with the given template_id

        Args:
            template_id (int): templateId of the target OcTemplate

        Raises:
            OcTemplateGetError: When the template_id was not provided
            OcTemplateGetError: When retrieving the OcTemplate failed

        Returns:
            dict[str, Any]: The data of the OcTemplate with the given template_id
        """
        if not template_id:
            raise OcTemplateGetError("No templateId for Template provided!")

        target_template_response: Response = self.oc_connector.oc_get(f"{TEMPLATE_URL}/{template_id}")

        if self.is_valid_response(target_template_response):
            return json.loads(target_template_response.text)

        raise OcTemplateGetError(f"Failed to retrieve OpenCelium Template with ID: {template_id}")


    def get_all_templates(self) -> Optional[list[dict[str, Any]]]:
        """
        Retrieves all busines templates from OpenCelium

        Raises:
            OcTemplateGetError: When retrieving the OcTemplates failed

        Returns:
            Optional[list[dict[str, Any]]]: list of all business templates from OpenCelium
        """
        all_templates_response: Response = self.oc_connector.oc_get(ALL_TEMPLATES_URL)

        # LOGGER.debug(f"[get_all_templates] response: {all_templates_response}")
        # LOGGER.debug(f"[get_all_templates] status_code: {all_templates_response.status_code}")
        # LOGGER.debug(f"[get_all_templates] headers: {all_templates_response.headers}")
        # LOGGER.debug(f"[get_all_templates] body: {all_templates_response.text}")

        if self.is_valid_response(all_templates_response):
            if all_templates_response.text:
                templates = json.loads(all_templates_response.text)

                # Filter DataGerry templates
                datagerry_templates: list[dict[str, Any]] = [
                    t for t in templates
                    if (
                        t.get("connection", {}).get("fromConnector", {})
                        .get("invoker", {}).get("name") == "DataGerry"
                        or
                        t.get("connection", {}).get("toConnector", {})
                        .get("invoker", {}).get("name") == "DataGerry"
                    )
                ]

                return datagerry_templates

            return None

        raise OcTemplateGetError("Failed to retrieve Business Templates from OpenCelium!")
