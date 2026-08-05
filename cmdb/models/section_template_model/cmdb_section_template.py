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
This module contains the implementation of CmdbSectionTemplate, which is representing
a section template in Datagarry.
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.section_template_model.cmdb_section_template_schema import get_cmdb_section_template_schema
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              CmdbSectionTemplate - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #

class CmdbSectionTemplate(CmdbDAO):
    """
    Implementation of CmdbSectionTemplate, a reusable section definition that CmdbTypes can include

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.sectionTemplates'
    MODEL = 'Section_Template'
    DEFAULT_VERSION = '1.0.0'
    REQUIRED_INIT_KEYS: list[str] = ['name', 'label','type', 'fields']

    SCHEMA: dict = get_cmdb_section_template_schema()

# ---------------------------------------------------- CONSTRUCTOR --------------------------------------------------- #

    def __init__(
        self,
        name: str,
        label: str,
        fields: list,
        type: str,
        is_global: bool = False,
        predefined: bool = False,
        **kwargs
    ) -> None:
        """
        Initialisation of a section template

        Args:
            name (str): unique name for section template
            label (str): Label which is displayed for this section template
            fields (list): List of fields which are part of this section
        """
        self.name: str = name
        self.label: str = label
        self.fields: list = fields
        self.is_global: bool = is_global
        self.predefined: bool = predefined
        self.type: str = type
        super().__init__(**kwargs)

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbSectionTemplate":
        """
        Returns an Instance of CmdbSectionTemplate

        Args:
            data (dict): Dict which contains parameters to initiate a CmdbSectionTemplate 

        Returns:
            (CmdbSectionTemplate): Instance of CmdbSectionTemplate with data from dict
        """
        return cls(
            public_id = data.get('public_id'),
            name = data.get('name'),
            label = data.get('label'),
            fields = data.get('fields'),
            is_global = data.get('is_global', False),
            predefined = data.get('predefined', False),
            type = data.get('type'),
        )


    @classmethod
    def to_json(cls, instance: "CmdbSectionTemplate") -> dict:
        """
        Convert a CmdbSectionTemplate instance to json conform data

        Args:
            instance (CmdbSectionTemplate): Instance of CmdbSectionTemplate

        Returns:
            (dict): Json conform dict
        """
        return {
            'public_id': instance.get_public_id(),
            'name': instance.name,
            'label': instance.label,
            'fields': instance.fields,
            'is_global': instance.is_global,
            'predefined': instance.predefined,
            'type': instance.type,
        }


    @classmethod
    def to_data(cls, instance: "CmdbSectionTemplate") -> dict:
        """
        Dict representation of a CmdbSectionTemplate
        TODO: check fields if correct
        """
        return {
            'public_id': instance['public_id'],
            'name': instance['name'],
            'label': instance['label'],
            'fields': instance['fields'],
            'is_global': instance['is_global'],
            'predefined': instance['predefined'],
            'type': instance['type'],
        }
