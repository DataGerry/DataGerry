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

from cmdb.class_schema.docapi_model.docapi_template_schema import get_docapi_template_schema
from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey
from cmdb.models.docapi_model import DocapiTemplateType
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.models.docapi_template import DocapiTemplateInitFromDataError, DocapiTemplateToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

class DocapiTemplate(CmdbDAO):
    """
    Docapi Template

    An HTML template rendered into a PDF for one CmdbObject. The document's keys are `DocapiTemplateKey`,
    which drives the shared `from_data` / `to_json` on CmdbDAO; `name` is the one key a stored document must
    carry, because the by-name route resolves a template by nothing else
    """
    COLLECTION = 'docapi.templates'

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [(DocapiTemplateKey.NAME.value, CmdbDAO.DAO_ASCENDING)], 'name': 'name', 'unique': True}
    ]

    SCHEMA: dict[str, Any] = get_docapi_template_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = DocapiTemplateKey
    INIT_FROM_DATA_ERROR = DocapiTemplateInitFromDataError
    TO_JSON_ERROR = DocapiTemplateToJsonError

    REQUIRED_INIT_KEYS: list[str] = [DocapiTemplateKey.NAME.value]

    #pylint: disable=too-many-arguments
    #pylint: disable=too-many-locals
    def __init__(
        self,
        *,
        public_id: int,
        name: str,
        label: str | None = None,
        description: str | None = None,
        active: bool | None = True,
        author_id: int | None = None,
        template_data: str | None = None,
        template_style: str | None = None,
        template_type: DocapiTemplateType | None = None,
        template_parameters: dict[str, Any] | None = None,
        header: dict[str, Any] | None = None,
        footer: dict[str, Any] | None = None,
        table_of_contents: dict[str, Any] | None = None,
        cover_page: dict[str, Any] | None = None,
        page_config: dict[str, Any] | None = None,
        **kwargs: Any
    ) -> None:
        """
        Initialises a DocapiTemplate

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this. Every
        optional value that arrives as None takes its default, so a document stored without a key reads the
        same as one built without it - `active` included, which is True. The routes build a template from
        the raw request body, so further keys are accepted and dropped; they never become attributes

        Args:
            public_id: public_id of this template
            name: name of this template
            label: label of this template
            description: description of this template
            active: is template active; None reads as True
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
            **kwargs: keys beyond the declared ones, ignored
        """
        del kwargs

        self.name: str = name
        self.label: str | None = label
        self.description: str | None = description
        self.active: bool = True if active is None else active
        self.author_id: int | None = author_id
        self.template_data: str | None = template_data
        self.template_style: str | None = template_style
        self.template_type: DocapiTemplateType = template_type or DocapiTemplateType.OBJECT
        self.template_parameters: dict[str, Any] | None = template_parameters
        self.header: dict[str, Any] = header or {}
        self.footer: dict[str, Any] = footer or {}
        self.table_of_contents: dict[str, Any] = table_of_contents or {}
        self.cover_page: dict[str, Any] = cover_page or {}
        self.page_config: dict[str, Any] = page_config or {}

        super().__init__(public_id=public_id)


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


    def get_template_data(self) -> str | None:
        """
        Get the template data
        
        Returns:
            str | None: Template data or None if not set
        """
        return self.template_data


    def get_template_style(self) -> str | None:
        """
        Get the style of this template
        
        Returns:
            str | None: Template style if set else None
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
