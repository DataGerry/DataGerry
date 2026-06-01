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
Loader and cache for the predefined section templates used by the DataGerry assistant

The predefined section templates (dg-modelspec, dg-network, dg-rackmounting, ...) are fetched from
the DB once per assistant run and reshaped into the intermediate form the ProfileTypeConstructor
consumes. A fresh deep copy is handed out on every request so that per-type mutations (e.g. marking
a field as summary) never leak between types that reuse the same template.
"""
from logging import Logger, getLogger
from typing import Any
from copy import deepcopy

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import SectionTemplatesManager

from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import FieldKey, SectionKey
from cmdb.framework.results import IterationResult

from .datagerry_assistant_constants import AssistantFieldKey, AssistantSectionKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Predefined section templates are stored in the DB with this flag set to True
PREDEFINED_TEMPLATE_FLAG: str = 'predefined'

# -------------------------------------------------------------------------------------------------------------------- #
#                                          PredefinedTemplateProvider - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class PredefinedTemplateProvider:
    """
    Loads the predefined section templates once and serves formatted, independent copies
    """

    def __init__(self, section_templates_manager: SectionTemplatesManager) -> None:
        """
        Args:
            section_templates_manager (SectionTemplatesManager): db interface used to load the
                                                                 predefined section templates once
        """
        self.section_templates_manager: SectionTemplatesManager = section_templates_manager
        self.predefined_templates: dict[str, dict[str, Any]] = self.__load_predefined_templates()

    def get_template(self, template_name: str, summary_fields: list[str] | None = None) -> dict[str, Any]:
        """
        Returns a fresh copy of a cached predefined section template

        A deep copy is returned so that marking fields as summary for one type does not leak into
        other types that reuse the same template later in the run.

        Args:
            template_name (str): name of the predefined section template
            summary_fields (list[str] | None, optional): Field names to flag as summary. Defaults to None.

        Returns:
            dict[str, Any]: The formatted section template
        """
        template_data: dict[str, Any] = deepcopy(self.predefined_templates[template_name])

        if summary_fields:
            section_fields: list[dict[str, Any]] = template_data[SectionKey.FIELDS]

            field: dict[str, Any]
            for field in section_fields:
                if field[FieldKey.NAME] in summary_fields:
                    field[AssistantFieldKey.IS_SUMMARY] = True

        return template_data

    def __load_predefined_templates(self) -> dict[str, dict[str, Any]]:
        """
        Loads all predefined section templates from the DB, keyed by template name

        Returns:
            dict[str, dict[str, Any]]: Mapping of template name to its formatted section-template data
        """
        formatted_list: dict[str, dict[str, Any]] = {}
        predefined_filter: dict[str, bool] = {PREDEFINED_TEMPLATE_FLAG: True}

        builder_params: BuilderParameters = BuilderParameters(predefined_filter)

        iteration_result: IterationResult[CmdbSectionTemplate] = self.section_templates_manager.iterate(builder_params)

        template_list: list[dict[str, Any]] = [template_.__dict__ for template_ in iteration_result.results]

        template: dict[str, Any]
        for template in template_list:
            template_name: str = template[SectionKey.NAME]
            formatted_list[template_name] = self.__format_template(template)

        return formatted_list

    def __format_template(self, template_data: dict[str, Any]) -> dict[str, Any]:
        """
        Reshapes a stored predefined section template into the form the TypeConstructor consumes

        Each field is split into the default keys (type/name/label) plus an 'extras' dict holding
        every other attribute.

        Args:
            template_data (dict[str, Any]): The stored predefined section template

        Returns:
            dict[str, Any]: Formatted section template data
        """
        formatted_template: dict[str, Any] = {
            SectionKey.NAME: template_data[SectionKey.NAME],
            SectionKey.LABEL: template_data[SectionKey.LABEL],
            AssistantSectionKey.GLOBAL_ID_NAME: template_data[SectionKey.NAME],
        }

        template_fields: list[dict[str, Any]] = template_data[SectionKey.FIELDS]
        formatted_fields: list[dict[str, Any]] = []
        default_keys: list[FieldKey] = [FieldKey.TYPE, FieldKey.NAME, FieldKey.LABEL]

        field: dict[str, Any]
        for field in template_fields:
            formatted_field: dict[str, Any] = {
                AssistantFieldKey.EXTRAS: {}
            }

            for key, value in field.items():
                if key in default_keys:
                    formatted_field[key] = value
                else:
                    formatted_field[AssistantFieldKey.EXTRAS][key] = value

            formatted_fields.append(formatted_field)

        formatted_template[SectionKey.FIELDS] = formatted_fields

        return formatted_template
