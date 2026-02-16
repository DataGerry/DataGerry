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
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              CmdbSectionTemplate - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #

class CmdbSectionTemplate(CmdbDAO):
    """
    The CMDB location is the basic data wrapper for storing and
    holding locations within the CMDB.

    Attributes:
        COLLECTION (str):    Name of the database collection.
        MODEL (Model):              Name of the DAO.
        DEFAULT_VERSION (str):      The default "starting" version number.
        SCHEMA (dict):              The validation schema for this DAO.
        INDEX_KEYS (list):          List of index keys for the database.
    """
    COLLECTION = 'framework.sectionTemplates'
    MODEL = 'Section_Template'
    DEFAULT_VERSION = '1.0.0'
    REQUIRED_INIT_KEYS = ['name', 'label','type', 'fields']

    SCHEMA: dict = {
        'public_id': {
            'type': 'integer'
        },
        'is_global': {
            'type': 'boolean',
            'default': False
        },
        'predefined': {
            'type': 'boolean',
            'default': False
        },
        'name': {
            'type': 'string',
            'required': True,
        },
        'label': {
            'type': 'string',
            'required': True,
        },
        'type': {
            'type': 'string',
            'default': 'section'
        },
        'fields': {
            'type': 'list',
            'required': True,
            'default': [],
        }
    }

    # this is required for compability with existing sections
    SECTION_TYPE = 'section'

# ---------------------------------------------------- CONSTRUCTOR --------------------------------------------------- #

    def __init__(self,
                 name: str,
                 label: str,
                 fields: list,
                 is_global: bool = False,
                 predefined: bool = False,
                 **kwargs):
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
        self.type: str = self.SECTION_TYPE
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
            is_global = data.get('is_global',False),
            predefined = data.get('predefined',False),
            type = cls.SECTION_TYPE,
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
