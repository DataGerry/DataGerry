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
Implementation of DocapiTemplate
"""
from typing import Any
from cmdb.framework.docapi.docapi_template.docapi_template_base import TemplateManagementBase
from cmdb.models.docapi_model import DocapiTemplateType
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.cmdb_object import NoPublicIDError
# -------------------------------------------------------------------------------------------------------------------- #
#TODO: REFACTOR-FIX (CmdbDAO as base)
class DocapiTemplate(TemplateManagementBase):
    """
    Docapi Template
    """
    COLLECTION = 'docapi.templates'
    MODEL = 'DocapiTemplate'

    INDEX_KEYS: list[Any] = [
        {'keys': [('name', CmdbDAO.DAO_ASCENDING)], 'name': 'name', 'unique': True}
    ]

    #pylint: disable=too-many-arguments
    #pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        name: str,
        label: str = None,
        description: str = None,
        active: bool = True,
        author_id: int = None,
        template_data = None,
        template_style = None,
        template_type: DocapiTemplateType = None,
        template_parameters = None,
        **kwargs
    ) -> None:
        """
        Args:
            name: name of this template
            label: label of this template
            active: is template active
            author_id: author of this template
            template_data: the content of this template (e.g. HTML string or reference to an HTML file)
            template_style: style of template
            template_type: type of docapi template
            template_parameters: parameter of this template depending on the type
            **kwargs: optional params
        """
        self.name: str = name
        self.label: str = label
        self.description: str = description
        self.active: bool = active
        self.author_id = author_id
        self.template_data = template_data
        self.template_style = template_style
        self.template_type: DocapiTemplateType = template_type or DocapiTemplateType.OBJECT
        self.template_parameters = template_parameters
        super().__init__(**kwargs)


    @classmethod
    def from_data(cls, data: dict) -> "DocapiTemplate":
        """
        Initialises a DocapiTemplate from a dict

        Args:
            data (dict): Data with which the DocapiTemplate should be initialised

        Returns:
            DocapiTemplate: DocapiTemplate with the given data
        """
        return cls(
            public_id = data['public_id'],
            name = data['name'],
            label = data.get('label', None),
            description = data.get('description', None),
            active = data.get('active', None),
            author_id = data.get('author_id', None),
            template_data = data.get('template_data', None),
            template_style = data.get('template_style', None),
            template_type = data.get('template_type', None),
            template_parameters = data.get('template_parameters', None),
        )


    @classmethod
    def to_json(cls, instance: "DocapiTemplate") -> dict:
        """
        Converts a DocapiTemplate into a json compatible dict

        Args:
            instance (DocapiTemplate): The DocapiTemplate which should be converted

        Returns:
            dict: Json compatible dict of the DocapiTemplate values
        """
        return {
            'public_id': instance.public_id,
            'name': instance.name,
            'label': instance.label,
            'description': instance.description,
            'active': instance.active,
            'author_id': instance.author_id,
            'template_data': instance.template_data,
            'template_style': instance.template_style,
            'template_type': instance.template_type,
            'template_parameters': instance.template_parameters
        }


    def get_public_id(self) -> int:
        """
        get the public id of current element

        Note:
            Since the models object is not initializable
            the child class object will inherit this function
            SHOULD NOT BE OVERWRITTEN!
        Returns:
            int: public id
        Raises:
            NoPublicIDError: if `public_id` is zero or not set
        """
        if self.public_id == 0 or self.public_id is None:
            raise NoPublicIDError("No public_id assigned!")

        return self.public_id


    def get_name(self) -> str:
        """
        Get the name of the template
        
        Returns:
            str: Display name or empty string if None
        """
        return self.name if self.name is not None else ""


    def get_label(self) -> str:
        """
        Get the label of the template
        
        Returns:
            str: Display label or empty string if None
        """
        return self.label if self.label is not None else ""


    def get_description(self) -> str:
        """
        Get the description of the template
        
        Returns:
            str: Description or empty string if None
        """
        return self.description if self.description is not None else ""


    def get_active(self) -> bool:
        """
        Get the active state of the template
        
        Returns:
            bool: True if active, otherwise False
        """
        return self.active is True


    def get_author_id(self) -> int | None:
        """
        Get the author ID of the template
        
        Returns:
            int | None: Author ID or None if not set
        """
        return self.author_id


    def get_template_data(self):
        """
        Get the template data
        
        Returns:
            Template data or None if not set
        """
        return self.template_data


    def get_template_style(self):
        """
        Get the style of this template
        
        Returns:
            Template style if set else None
        """
        return self.template_style
