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
This module contains the implementation of ProfileTypeConstructor
"""
import logging
import random
from datetime import datetime, timezone

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import SectionTemplatesManager

from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.framework.results import IterationResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            ProfileTypeConstructor - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ProfileTypeConstructor:
    """Creates valid section and field data for types in order to be stored in the DB"""

    def __init__(self, section_templates_manager: SectionTemplatesManager):
        self.section_templates_manager = section_templates_manager
        self.predefined_templates = self.__get_predefined_templates()
        self.type_config: dict = {}

# --------------------------------------------------- TYPE BUILDER --------------------------------------------------- #

    def create_type_config(self,
                           type_data: list,
                           name: str,
                           label: str,
                           icon: str,
                           selectable_as_parent: bool = True) -> dict:
        """
        Initialses the creation of the CmdbType. This method should always be called First when
        creating a new CmdbType with the TypeConstructor.

        Args:
            type_data (list): Sections with fields which should be added to this type
            name (str): name for the type
            label (str): label for the type
            icon (str): icon for the type
            selectable_as_parent (bool, optional): Sets if this type can be selected as parent for a location.
                                                   Defaults to True.

        Returns:
            dict: The initialized CmdbType
        """
        self.__create_type_body(name, label,icon,selectable_as_parent)
        self.__create_sections_and_fields(type_data)

        return self.type_config


    def __create_type_body(self, name: str, label: str, icon: str, selectable_as_parent: bool = True) -> None:
        """
        Genereates a CmdbType skeleton for the current type

        Args:
            name (str): name for the type
            label (str): label for the type
            icon (str): icon for the type
            selectable_as_parent (bool, optional): Sets if this type is selectable as parent for a location.
                                                   Defaults to True.
        """
        self.type_config = {
            "name": name,
            "selectable_as_parent": selectable_as_parent,
            "global_template_ids": [],
            "active": True,
            "author_id": 1,
            "creation_time": datetime.now(timezone.utc),
            "editor_id": None,
            "last_edit_time": None,
            "label": label,
            "version": "1.0.0",
            "description": None,
            "render_meta": self.__create_render_meta(icon),
            "ci_explorer_label": None,
            "ci_explorer_color": f'#{random.randint(0, 0xFFFFFF):06X}',
            "fields": [
            ],
            "acl": {
                "activated": False,
                "groups": {
                    "includes": {}
                }
            }
        }


    def __create_render_meta(self, icon: str) -> dict:
        """
        Creates a 'render_meta' skeleton for the current type
        Args:
            icon (str): The icon which the type should have

        Returns:
            dict: Created skeleton of the 'render_meta'
        """
        return  {
                "icon": icon,
                "sections": [
                ],
                "externals": [
                ],
                "summary": {
                    "fields": [
                    ]
                }
            }


    def __create_sections_and_fields(self, type_data: list[dict]) -> None:
        """
        Sets all sections and fields for the type

        Args:
            type_data (list[dict]): List containing sections with fields which should set for the current type
        """
        new_section: dict
        for new_section in type_data:
            section_name: str = new_section['name']
            section_label: str = new_section['label']
            section_fields: list = new_section['fields']

            if 'global_id_name' in new_section.keys():
                global_id_name = new_section['global_id_name']
                self.__set_predefined_template_id(global_id_name)

            self.__set_section(section_name, section_label)
            self.__set_fields(section_fields, section_name)

# ------------------------------------------------- SECTION HANDLING ------------------------------------------------- #

    def __set_section(self, section_name: str, section_label: str) -> None:
        """
        Sets a basic section skeleton without fields for the current type in 'render_meta'
        
        Args:
            section_name (str): name for the section
            section_label (str): label for the section
        """
        default_section: dict = {
            "type": "section",
            "name": section_name,
            "label": section_label,
            "fields": [
            ]
        }

        type_sections: list = list(self.type_config['render_meta']['sections'])
        type_sections.append(default_section)

        self.type_config['render_meta']['sections'] = type_sections

# ---------------------------------------------- SECTION FIELD HANDLING ---------------------------------------------- #

    def __set_fields(self, new_fields:list, section_name: str) -> None:
        """
        Sets all given fields in the section with the name 'section_name'

        Args:
            new_fields (list): List of fields which should be set for a type
            section_name (str): name of the section which should contain the fields
        """
        for new_field_params in new_fields:
            self.__set_type_field(new_field_params, section_name)


    def __set_type_field(self, field_params: dict, section_name: str) -> None:
        """
        Configures a section fields and sets it for the type_config in 'fields', 'render_meta' and 'summary' according
        to the configuration

        Args:
            field_params (dict): All data which the field should have
            section_name (str): 'name' of the section for which this field is used
        """
        is_summary:bool = False
        extras: dict = {}

        field_type: str = field_params['type']
        field_name: str = field_params['name']
        field_label: str = field_params['label']

        if 'is_summary' in field_params.keys():
            is_summary = field_params['is_summary']

        if 'extras' in field_params.keys():
            extras = field_params['extras']


        type_field: dict = {
            "type": field_type,
            "name": field_name,
            "label": field_label
        }

        if extras:
            type_field = self.__set_type_field_extras(type_field, extras)

        # Set field on type config
        type_fields: list = self.type_config['fields']
        type_fields.append(type_field)

        self.type_config['fields'] = type_fields

        # Set field on section
        type_sections: list = list(self.type_config['render_meta']['sections'])

        index: int = 0
        for section in type_sections:
            if section['name'] == section_name:
                section_fields: list = list(section['fields'])
                section_fields.append(field_name)
                section['fields'] = section_fields
                type_sections[index] = section

                self.type_config['render_meta']['sections'] = type_sections
                break

            index = index +1

        # Set field as summary if summary
        if is_summary:
            self.__set_summary_field(field_name)


    def __set_type_field_extras(self, type_field: dict, extras: dict) -> dict:
        """
        Sets additional properties for a field (other than type, name and label)
        
        Args:
            type_field (dict): The field which needs the extra properties to be set
            extras (dict): Key-Value pairs of extra properties. The accepted keys are
                           in the list 'extra_keys'

        Returns:
            dict: The updated version of the given field
        """

        extra_keys = ['options', 'helperText', 'regex', 'ref_types','summaries']

        for extra_key in extra_keys:
            if extra_key in extras.keys():
                type_field[extra_key] = extras[extra_key]

        return type_field

# ------------------------------------------- CONDITIONAL SECTIONS HANDLING ------------------------------------------ #

    def add_conditional_sections(self, conditional_sections: list) -> None:
        """
        Adds additional sections to the type if the all given conditionIDs are not None
        
        Args:
            conditional_sections (list): List of sections which should be created
        """
        affirmed_sections: list = []

        for conditional_section in conditional_sections:
            conditional_ids: list = conditional_section['conditional_ids']

            if self.__check_conditional_ids(conditional_ids):
                conditional_section = self.__set_conditional_ref(conditional_section, conditional_ids)
                affirmed_sections.append(conditional_section)

        self.__create_sections_and_fields(affirmed_sections)


    def create_conditional_ref_section(self,
                                       field_name: str,
                                       field_label: str,
                                       section_name:str,
                                       section_label: str,
                                       conditional_ids: list) -> dict:
        """
        Generates a conditional section which has one ref-field. The referenced typeIDs
        are requested and can be 'None'. If any of the requested IDs is None then the section
        will not be created.

        Args:
            field_name (str): name for the ref-field
            field_label (str): label for the ref-field
            section_name (str): name for the section
            section_label (str): label for the section
            conditional_ids (list): List of required type IDs which should be referenced

        Returns:
            dict: _description_
        """
        return {
            "conditional_ids": conditional_ids,
            "name": section_name,
            "label": section_label,
            "fields": [
                {
                    "type": "ref",
                    "name": field_name,
                    "label": field_label,
                    "extras":{
                        "ref_types": [],
                        "summaries": []
                    }

                }
            ]
        }


    def __set_conditional_ref(self, section: dict, conditional_ids: list) -> dict:
        """
        Sets the reference property of the ref-field for a conditional section
        Args:
            section (dict): target section which the ref-field
            conditional_ids (list): public_id's of types which should be referenced

        Returns:
            dict: The updated version of the given section
        """
        section['fields'][0]['extras']['ref_types'] = conditional_ids

        return section


    def __check_conditional_ids(self, conditional_ids: list) -> bool:
        """
        Checks if all requested public_ids exist before the conditional section is created
        
        Args:
            conditional_ids (list): list with all requested ids

        Returns:
            bool: True if all IDs are present, else False
        """
        for conditional_id in conditional_ids:
            if not conditional_id:
                return False

        return True

# --------------------------------------- PREDEFINED SECTION TEMPLATES HANDLING -------------------------------------- #

    def get_predefined_template_data(self, template_name: str, summary_fields: list[str] = None) -> dict:
        """
        Retrives a predefined section template
        Args:
            template_name (str): name of the predefined section template
            summary_fields (list[str], optional): List of field names which should be set as summary.
                                                  Defaults to None.

        Returns:
            dict: The formatted section template 
        """
        template_data: dict = self.predefined_templates[template_name]

        section_fields: list[dict] = template_data['fields']

        if summary_fields:
            for field in section_fields:
                if field['name'] in summary_fields:
                    field['is_summary'] = True

        return self.predefined_templates[template_name]


    def __get_predefined_templates(self):
        """Retrives all predefined section templates from the DB"""
        formatted_list: dict = {}
        predefined_filter = {'predefined': True}

        builder_params: BuilderParameters = BuilderParameters(predefined_filter)

        iteration_result: IterationResult[CmdbSectionTemplate] = self.section_templates_manager.iterate(builder_params)

        template_list: list[dict] = [template_.__dict__ for template_ in iteration_result.results]

        for template in template_list:
            template_name = template['name']
            formatted_list[template_name] = self.__format_predefined_template_data(template)

        return formatted_list


    def __set_predefined_template_id(self, template_id_name: str) -> None:
        """
        Sets the name of the predefined section template on the current type

        Args:
            template_id_name (str): name of the predefined section template
        """
        global_ids= list(self.type_config['global_template_ids'])
        global_ids.append(template_id_name)
        self.type_config['global_template_ids'] = global_ids


    def __format_predefined_template_data(self, template_data: dict)-> dict:
        """
        Formats the API response containing the predefined section templates so that
        they can be used by the TypeConstructor

        Args:
            template_data (dict): The predefined section template data

        Returns:
            dict: Formatted section template data
        """
        formatted_template: dict = {
            "name": template_data['name'],
            "label": template_data['label'],
            "global_id_name": template_data['name'],
        }

        template_fields: list = template_data['fields']
        formatted_fields: list = []
        default_keys: list = ['type', 'name', 'label']

        field: dict
        for field in template_fields:
            formatted_field = {
                "extras": {}
            }

            for key, value in field.items():
                if key in default_keys:
                    formatted_field[key] = value
                else:
                    formatted_field['extras'][key] = value

            formatted_fields.append(formatted_field)

        formatted_template['fields'] = formatted_fields

        return formatted_template

# ------------------------------------------------- SUMMARY HANDLING ------------------------------------------------- #

    def __set_summary_field(self, field_name: str) -> None:
        """
        Sets the given field_name as a summary field of the current type
        Args:
            field_name (str): name of the field which should be set as a summary field
        """
        type_summary = list(self.type_config['render_meta']['summary']['fields'])
        type_summary.append(field_name)

        self.type_config['render_meta']['summary']['fields'] = type_summary
