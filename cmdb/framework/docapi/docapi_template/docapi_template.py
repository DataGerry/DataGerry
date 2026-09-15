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
Implementation of DocapiTemplate
"""
from typing import Any
from cmdb.framework.docapi.docapi_template.docapi_template_base import TemplateManagementBase
from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey
from cmdb.models.docapi_model import DocapiTemplateType
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.cmdb_object import NoPublicIDError
# -------------------------------------------------------------------------------------------------------------------- #
# NOTE: this model extends TemplateManagementBase rather than CmdbDAO; migrating it onto CmdbDAO is
#       tracked in the discussion backlog (a cross-model refactor), not done here.
class DocapiTemplate(TemplateManagementBase):
    """
    Docapi Template
    """
    COLLECTION = 'docapi.templates'

    INDEX_KEYS: list[Any] = [
        {'keys': [('name', CmdbDAO.DAO_ASCENDING)], 'name': 'name', 'unique': True}
    ]

    #pylint: disable=too-many-arguments
    #pylint: disable=too-many-positional-arguments
    #pylint: disable=too-many-locals
    def __init__(
        self,
        name: str,
        label: str = None,
        description: str = None,
        active: bool = True,
        author_id: int = None,
        template_data: str = None,
        template_style: str = None,
        template_type: DocapiTemplateType = None,
        template_parameters = None,
        header: dict[str, Any] = None,
        footer: dict[str, Any] = None,
        table_of_contents: dict[str, Any] = None,
        cover_page: dict[str, Any] = None,
        page_config: dict[str, Any] = None,
        **kwargs
    ) -> None:
        """
        Args:
            name: name of this template
            label: label of this template
            description: description of this template
            active: is template active
            author_id: author of this template
            template_data: the content of this template (e.g. HTML string or reference to an HTML file)
            template_style: style of template
            template_type: type of docapi template
            template_parameters: parameter of this template depending on the type
            header: header component config (activated / config / content)
            footer: footer component config (activated / config / content)
            table_of_contents: table-of-contents component config
            cover_page: cover-page component config (activated / content)
            page_config: page config (margins etc.)
            **kwargs: optional params
        """
        self.name: str = name
        self.label: str = label
        self.description: str = description
        self.active: bool = active
        self.author_id: int = author_id
        self.template_data: str = template_data
        self.template_style: str = template_style
        self.template_type: DocapiTemplateType = template_type or DocapiTemplateType.OBJECT
        self.template_parameters = template_parameters
        self.header: dict[str, Any] = header or {}
        self.footer: dict[str, Any] = footer or {}
        self.table_of_contents: dict[str, Any] = table_of_contents or {}
        self.cover_page: dict[str, Any] = cover_page or {}
        self.page_config: dict[str, Any] = page_config or {}

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
            public_id = data[DocapiTemplateKey.PUBLIC_ID],
            name = data[DocapiTemplateKey.NAME],
            label = data.get(DocapiTemplateKey.LABEL, None),
            description = data.get(DocapiTemplateKey.DESCRIPTION, None),
            active = data.get(DocapiTemplateKey.ACTIVE, None),
            author_id = data.get(DocapiTemplateKey.AUTHOR_ID, None),
            template_data = data.get(DocapiTemplateKey.TEMPLATE_DATA, None),
            template_style = data.get(DocapiTemplateKey.TEMPLATE_STYLE, None),
            template_type = data.get(DocapiTemplateKey.TEMPLATE_TYPE, None),
            template_parameters = data.get(DocapiTemplateKey.TEMPLATE_PARAMETERS, None),
            header = data.get(DocapiTemplateKey.HEADER, {}),
            footer = data.get(DocapiTemplateKey.FOOTER, {}),
            table_of_contents = data.get(DocapiTemplateKey.TABLE_OF_CONTENTS, {}),
            cover_page = data.get(DocapiTemplateKey.COVER_PAGE, {}),
            page_config = data.get(DocapiTemplateKey.PAGE_CONFIG, {}),
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
            DocapiTemplateKey.PUBLIC_ID: instance.public_id,
            DocapiTemplateKey.NAME: instance.name,
            DocapiTemplateKey.LABEL: instance.label,
            DocapiTemplateKey.DESCRIPTION: instance.description,
            DocapiTemplateKey.ACTIVE: instance.active,
            DocapiTemplateKey.AUTHOR_ID: instance.author_id,
            DocapiTemplateKey.TEMPLATE_DATA: instance.template_data,
            DocapiTemplateKey.TEMPLATE_STYLE: instance.template_style,
            DocapiTemplateKey.TEMPLATE_TYPE: instance.template_type,
            DocapiTemplateKey.TEMPLATE_PARAMETERS: instance.template_parameters,
            DocapiTemplateKey.HEADER: instance.header,
            DocapiTemplateKey.FOOTER: instance.footer,
            DocapiTemplateKey.TABLE_OF_CONTENTS: instance.table_of_contents,
            DocapiTemplateKey.COVER_PAGE: instance.cover_page,
            DocapiTemplateKey.PAGE_CONFIG: instance.page_config,
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


    def get_template_data(self) -> str:
        """
        Get the template data
        
        Returns:
            str: Template data or None if not set
        """
        return self.template_data


    def get_template_style(self) -> str:
        """
        Get the style of this template
        
        Returns:
            Template style if set else None
        """
        return self.template_style


    def get_footer(self) -> dict[str, Any]:
        """
        Get the footer of the template
        
        Returns:
            dict[str, Any]: The footer data of the template
        """
        return self.footer


    def get_header(self) -> dict[str, Any]:
        """
        Get the header of the template
        
        Returns:
            dict[str, Any]: The header data of the template
        """
        return self.header


    def get_table_of_contents(self) -> dict[str, Any]:
        """
        Get the toc of the template
        
        Returns:
            dict[str, Any]: The toc data of the template
        """
        return self.table_of_contents


    def get_cover_page(self) -> dict[str, Any]:
        """
        Get the cover page data of the template
        
        Returns:
            dict[str, Any]: The cover page data of the template
        """
        return self.cover_page


    def get_page_config(self) -> dict[str, Any]:
        """
        Get the page config data of the template
        
        Returns:
            dict[str, Any]: The page config data of the template
        """
        return self.page_config
