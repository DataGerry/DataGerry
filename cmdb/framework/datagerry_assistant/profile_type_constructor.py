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
Builder that turns the assistant's section/field definitions into insertable CmdbType dicts

ProfileTypeConstructor assembles a CmdbType document from the intermediate section/field
representation the profiles hand it: it builds the type skeleton, the flat 'fields' list, the
'render_meta' section layout and the summary list, and appends conditional reference sections whose
target types exist. It also wraps the canonical SpecialType blueprints (from SchemaProvider) into
full CmdbType configs. Predefined section templates are resolved through an injected
PredefinedTemplateProvider, keeping all DB access out of this builder.
"""
from logging import Logger, getLogger
from typing import Any
import random
from datetime import datetime, timezone

from cmdb.models.type_model import FieldKey, SectionKey, FieldType, SectionType, TypeSchemaKey

from .predefined_template_provider import PredefinedTemplateProvider
from .datagerry_assistant_constants import (
    AssistantFieldKey,
    AssistantSectionKey,
    TypeConfigKey,
    RenderMetaKey,
    TypeDefault,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Extra-property keys that may be lifted from a field's 'extras' dict onto the persisted field
FIELD_EXTRA_KEYS: list[str] = [
    FieldKey.OPTIONS,
    AssistantFieldKey.HELPER_TEXT,
    FieldKey.REGEX,
    FieldKey.REF_TYPES,
    AssistantFieldKey.SUMMARIES,
]

# -------------------------------------------------------------------------------------------------------------------- #
#                                            ProfileTypeConstructor - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ProfileTypeConstructor:
    """Creates valid section and field data for types in order to be stored in the DB"""

    def __init__(self, template_provider: PredefinedTemplateProvider) -> None:
        """
        Args:
            template_provider (PredefinedTemplateProvider): Provider of the predefined section templates
        """
        self.template_provider: PredefinedTemplateProvider = template_provider
        self.type_config: dict[str, Any] = {}

# --------------------------------------------------- TYPE BUILDER --------------------------------------------------- #

    def create_type_config(self,
                           type_data: list[dict[str, Any]],
                           name: str,
                           label: str,
                           icon: str,
                           selectable_as_parent: bool = True) -> dict[str, Any]:
        """
        Initialises the creation of the CmdbType. Must always be called first when creating a new
        CmdbType with the TypeConstructor, since it (re)initialises the internal type_config.

        Args:
            type_data (list[dict[str, Any]]): Sections (each with its fields) to add to this type
            name (str): name for the type
            label (str): label for the type
            icon (str): icon for the type
            selectable_as_parent (bool, optional): Whether the type can be a location parent.
                                                   Defaults to True.

        Returns:
            dict[str, Any]: The initialized CmdbType config
        """
        self.__create_type_body(name, label, icon, selectable_as_parent)
        self.__create_sections_and_fields(type_data)

        return self.type_config


    def create_special_type_config(self,
                                   schema: dict[str, Any],
                                   name: str,
                                   label: str,
                                   icon: str,
                                   selectable_as_parent: bool = True) -> dict[str, Any]:
        """
        Wraps a SpecialType section/field blueprint into a full, insertable CmdbType config

        The blueprint (from SchemaProvider) already stores its sections in the render_meta layout
        (each section lists its field names) and its fields in the persisted field-list shape, so
        both are assigned directly. The first field - the SpecialType's name field - is marked as
        the summary field. Reference fields keep their empty 'ref_types'; the cross-wiring to the
        other SpecialTypes happens post-insert via handle_special_types.

        Args:
            schema (dict[str, Any]): SpecialType blueprint with 'special_type', 'sections' and 'fields'
            name (str): name for the type
            label (str): label for the type
            icon (str): icon for the type
            selectable_as_parent (bool, optional): Whether the type can be a location parent.
                                                   Defaults to True.

        Returns:
            dict[str, Any]: The initialized CmdbType config carrying the 'special_type' marker
        """
        self.__create_type_body(name, label, icon, selectable_as_parent)

        self.type_config[TypeSchemaKey.SPECIAL_TYPE] = schema[TypeSchemaKey.SPECIAL_TYPE]
        self.type_config[TypeConfigKey.RENDER_META][RenderMetaKey.SECTIONS] = schema[TypeSchemaKey.SECTIONS]
        self.type_config[TypeConfigKey.FIELDS] = schema[TypeSchemaKey.FIELDS]

        schema_fields: list[dict[str, Any]] = schema[TypeSchemaKey.FIELDS]

        if schema_fields:
            summary: dict[str, Any] = self.type_config[TypeConfigKey.RENDER_META][RenderMetaKey.SUMMARY]
            summary[RenderMetaKey.FIELDS] = [schema_fields[0][FieldKey.NAME]]

        return self.type_config


    def __create_type_body(self, name: str, label: str, icon: str, selectable_as_parent: bool = True) -> None:
        """
        Generates a CmdbType skeleton for the current type

        Args:
            name (str): name for the type
            label (str): label for the type
            icon (str): icon for the type
            selectable_as_parent (bool, optional): Whether the type can be a location parent.
                                                   Defaults to True.
        """
        color_value: int = random.randint(0, TypeDefault.CI_EXPLORER_COLOR_MAX)
        ci_explorer_color: str = f'#{color_value:0{TypeDefault.CI_EXPLORER_COLOR_HEX_WIDTH}X}'

        self.type_config = {
            TypeConfigKey.NAME: name,
            TypeConfigKey.SELECTABLE_AS_PARENT: selectable_as_parent,
            TypeConfigKey.GLOBAL_TEMPLATE_IDS: [],
            TypeConfigKey.ACTIVE: True,
            TypeConfigKey.AUTHOR_ID: TypeDefault.AUTHOR_ID,
            TypeConfigKey.CREATION_TIME: datetime.now(timezone.utc),
            TypeConfigKey.EDITOR_ID: None,
            TypeConfigKey.LAST_EDIT_TIME: None,
            TypeConfigKey.LABEL: label,
            TypeConfigKey.VERSION: TypeDefault.VERSION,
            TypeConfigKey.DESCRIPTION: None,
            TypeConfigKey.RENDER_META: self.__create_render_meta(icon),
            TypeConfigKey.CI_EXPLORER_LABEL: None,
            TypeConfigKey.CI_EXPLORER_COLOR: ci_explorer_color,
            TypeConfigKey.FIELDS: [],
            TypeConfigKey.ACL: {
                "activated": False,
                "groups": {
                    "includes": {}
                }
            }
        }


    def __create_render_meta(self, icon: str) -> dict[str, Any]:
        """
        Creates a 'render_meta' skeleton for the current type

        Args:
            icon (str): The icon which the type should have

        Returns:
            dict[str, Any]: Created skeleton of the 'render_meta'
        """
        return {
            RenderMetaKey.ICON: icon,
            RenderMetaKey.SECTIONS: [],
            RenderMetaKey.EXTERNALS: [],
            RenderMetaKey.SUMMARY: {
                RenderMetaKey.FIELDS: []
            }
        }


    def __create_sections_and_fields(self, type_data: list[dict[str, Any]]) -> None:
        """
        Sets all sections and their fields on the current type

        Args:
            type_data (list[dict[str, Any]]): Sections (each with its fields) to set on the type
        """
        new_section: dict[str, Any]
        for new_section in type_data:
            section_name: str = new_section[SectionKey.NAME]
            section_label: str = new_section[SectionKey.LABEL]
            section_fields: list[dict[str, Any]] = new_section[SectionKey.FIELDS]

            if AssistantSectionKey.GLOBAL_ID_NAME in new_section.keys():
                global_id_name: str = new_section[AssistantSectionKey.GLOBAL_ID_NAME]
                self.__set_predefined_template_id(global_id_name)

            self.__set_section(section_name, section_label)
            self.__set_fields(section_fields, section_name)

# ------------------------------------------------- SECTION HANDLING ------------------------------------------------- #

    def __set_section(self, section_name: str, section_label: str) -> None:
        """
        Appends an empty section skeleton (no fields yet) to the current type's 'render_meta'

        Args:
            section_name (str): name for the section
            section_label (str): label for the section
        """
        default_section: dict[str, Any] = {
            SectionKey.TYPE: SectionType.SECTION,
            SectionKey.NAME: section_name,
            SectionKey.LABEL: section_label,
            SectionKey.FIELDS: []
        }

        self.type_config[TypeConfigKey.RENDER_META][RenderMetaKey.SECTIONS].append(default_section)

# ---------------------------------------------- SECTION FIELD HANDLING ---------------------------------------------- #

    def __set_fields(self, new_fields: list[dict[str, Any]], section_name: str) -> None:
        """
        Sets all given fields on the section named 'section_name'

        Args:
            new_fields (list[dict[str, Any]]): Fields to set on the type
            section_name (str): name of the section which should contain the fields
        """
        new_field_params: dict[str, Any]
        for new_field_params in new_fields:
            self.__set_type_field(new_field_params, section_name)


    def __set_type_field(self, field_params: dict[str, Any], section_name: str) -> None:
        """
        Configures a field and records it on the type_config: in the flat 'fields' list, under its
        section in 'render_meta', and in the summary list when flagged as a summary field

        Args:
            field_params (dict[str, Any]): All data the field should carry
            section_name (str): 'name' of the section this field belongs to
        """
        is_summary: bool = False
        extras: dict[str, Any] = {}

        field_type: str = field_params[FieldKey.TYPE]
        field_name: str = field_params[FieldKey.NAME]
        field_label: str = field_params[FieldKey.LABEL]

        if AssistantFieldKey.IS_SUMMARY in field_params.keys():
            is_summary = field_params[AssistantFieldKey.IS_SUMMARY]

        if AssistantFieldKey.EXTRAS in field_params.keys():
            extras = field_params[AssistantFieldKey.EXTRAS]

        type_field: dict[str, Any] = {
            FieldKey.TYPE: field_type,
            FieldKey.NAME: field_name,
            FieldKey.LABEL: field_label
        }

        if extras:
            type_field = self.__set_type_field_extras(type_field, extras)

        # Add to the flat field list
        self.type_config[TypeConfigKey.FIELDS].append(type_field)

        # Add the field name under its section in render_meta
        section: dict[str, Any]
        for section in self.type_config[TypeConfigKey.RENDER_META][RenderMetaKey.SECTIONS]:
            if section[SectionKey.NAME] == section_name:
                section[SectionKey.FIELDS].append(field_name)
                break

        if is_summary:
            self.__set_summary_field(field_name)


    def __set_type_field_extras(self, type_field: dict[str, Any], extras: dict[str, Any]) -> dict[str, Any]:
        """
        Lifts the accepted extra properties (other than type, name and label) onto a field

        Args:
            type_field (dict[str, Any]): The field to receive the extra properties
            extras (dict[str, Any]): Key-Value pairs of extra properties. Only the keys listed in
                                     FIELD_EXTRA_KEYS are copied over

        Returns:
            dict[str, Any]: The updated field
        """
        for extra_key in FIELD_EXTRA_KEYS:
            if extra_key in extras.keys():
                type_field[extra_key] = extras[extra_key]

        return type_field

# ------------------------------------------- CONDITIONAL SECTIONS HANDLING ------------------------------------------ #

    def add_conditional_sections(self, conditional_sections: list[dict[str, Any]]) -> None:
        """
        Adds each conditional section to the type, but only when all of its conditional ids are set

        Args:
            conditional_sections (list[dict[str, Any]]): Candidate sections, each carrying a
                                                         'conditional_ids' list (see
                                                         create_conditional_ref_section)
        """
        affirmed_sections: list[dict[str, Any]] = []

        conditional_section: dict[str, Any]
        for conditional_section in conditional_sections:
            conditional_ids: list[int | None] = conditional_section[AssistantSectionKey.CONDITIONAL_IDS]

            if self.__check_conditional_ids(conditional_ids):
                conditional_section = self.__set_conditional_ref(conditional_section, conditional_ids)
                affirmed_sections.append(conditional_section)

        self.__create_sections_and_fields(affirmed_sections)


    def create_conditional_ref_section(self,
                                       field_name: str,
                                       field_label: str,
                                       section_name: str,
                                       section_label: str,
                                       conditional_ids: list[int | None]) -> dict[str, Any]:
        """
        Generates a conditional section holding a single reference field

        The referenced type ids may be None (the slot's type was not created). When any id is None
        the section is skipped by add_conditional_sections.

        Args:
            field_name (str): name for the ref-field
            field_label (str): label for the ref-field
            section_name (str): name for the section
            section_label (str): label for the section
            conditional_ids (list[int | None]): Required type ids to reference; any None skips the section

        Returns:
            dict[str, Any]: A conditional section dict carrying its 'conditional_ids' alongside the
                            section/field layout, ready for add_conditional_sections()
        """
        return {
            AssistantSectionKey.CONDITIONAL_IDS: conditional_ids,
            SectionKey.NAME: section_name,
            SectionKey.LABEL: section_label,
            SectionKey.FIELDS: [
                {
                    FieldKey.TYPE: FieldType.REFERENCE,
                    FieldKey.NAME: field_name,
                    FieldKey.LABEL: field_label,
                    AssistantFieldKey.EXTRAS: {
                        FieldKey.REF_TYPES: [],
                        AssistantFieldKey.SUMMARIES: []
                    }
                }
            ]
        }


    def __set_conditional_ref(self, section: dict[str, Any], conditional_ids: list[int]) -> dict[str, Any]:
        """
        Sets the 'ref_types' of a conditional section's single reference field

        Args:
            section (dict[str, Any]): Target section holding the ref-field
            conditional_ids (list[int]): public_ids of the types to reference

        Returns:
            dict[str, Any]: The updated section
        """
        section[SectionKey.FIELDS][0][AssistantFieldKey.EXTRAS][FieldKey.REF_TYPES] = conditional_ids

        return section


    def __check_conditional_ids(self, conditional_ids: list[int | None]) -> bool:
        """
        Checks that every requested public_id is set before its conditional section is created

        Args:
            conditional_ids (list[int | None]): All requested ids

        Returns:
            bool: True if every id is truthy, else False
        """
        for conditional_id in conditional_ids:
            if not conditional_id:
                return False

        return True

# --------------------------------------- PREDEFINED SECTION TEMPLATES HANDLING -------------------------------------- #

    def get_predefined_template_data(self,
                                     template_name: str,
                                     summary_fields: list[str] | None = None) -> dict[str, Any]:
        """
        Returns a fresh copy of a predefined section template via the PredefinedTemplateProvider

        Args:
            template_name (str): name of the predefined section template
            summary_fields (list[str] | None, optional): Field names to flag as summary. Defaults to None.

        Returns:
            dict[str, Any]: The formatted section template
        """
        return self.template_provider.get_template(template_name, summary_fields)


    def __set_predefined_template_id(self, template_id_name: str) -> None:
        """
        Records a predefined section template's name in the current type's 'global_template_ids'

        Args:
            template_id_name (str): name of the predefined section template
        """
        self.type_config[TypeConfigKey.GLOBAL_TEMPLATE_IDS].append(template_id_name)

# ------------------------------------------------- SUMMARY HANDLING ------------------------------------------------- #

    def __set_summary_field(self, field_name: str) -> None:
        """
        Appends 'field_name' to the current type's summary field list

        Args:
            field_name (str): name of the field to mark as a summary field
        """
        summary: dict[str, Any] = self.type_config[TypeConfigKey.RENDER_META][RenderMetaKey.SUMMARY]
        summary[RenderMetaKey.FIELDS].append(field_name)
