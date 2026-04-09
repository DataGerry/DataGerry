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
Represents an ObjectDocumentGenerator in DataGerry
"""
from logging import Logger, getLogger
from typing import Any
from io import BytesIO
from datetime import datetime

from cmdb.manager import ObjectsManager

from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.docapi.docapi_template.docgen_cover_page import CoverPage
from cmdb.framework.docapi.docapi_template.docgen_toc import TableOfContents
from cmdb.framework.docapi.docapi_template.docgen_header_footer import PageHeaderFooter
from cmdb.models.docapi_model.template_engine import TemplateEngine
from cmdb.models.docapi_model.pdf_document_type import PdfDocumentType
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.models.docapi_model.default_template_data import DefaultTemplateData
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.user_model.cmdb_user import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            ObjectDocumentGenerator - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectDocumentGenerator:
    """
    A generator for creating document files from templates
    """
    # Default CSS to ensure consistent document styling in TinyMCE and the final PDF
    default_css: str = """
        img {
            zoom: 70%;
        }

        td {
            padding: 1px;
        }

        .report-table {
            width: 100%;
            border-collapse: collapse;
        }

        .report-table th,
        .report-table td {
            border: 1px solid #444;
            padding: 2px;
            font-size: 7pt;
            word-wrap: break-word;
        }

        .report-table th {
            background-color: #f0f0f0;
            font-weight: bold;
            text-align: left;
        }
    """

    def __init__(
        self,
        template: DocapiTemplate,
        cmdb_render_object: RenderResult,
        doctype: PdfDocumentType,
        objects_manager: ObjectsManager,
        request_user: CmdbUser = None
        ) -> None:
        """
        Initializes the ObjectDocumentGenerator

        Args:
            template (DocapiTemplate): The template object containing structure and styling
            cmdb_object (RenderResult): The CmdbObject RenderResult
            doctype (PdfDocumentType): The document type that determines the final output format
            objects_manager (ObjectsManager): The manager responsible for CmdbObject operations
        """
        self.template: DocapiTemplate = template
        self.cmdb_render_object: RenderResult = cmdb_render_object
        self.doctype: PdfDocumentType = doctype
        self.objects_manager: ObjectsManager = objects_manager
        self.request_user: CmdbUser = request_user


    def generate_doc(self) -> BytesIO:
        """
        Generates a document by rendering the template with CmdbObject data

        The method fetches relevant data, applies it to the template,
        constructs an HTML document, and then generates the final document

        Returns:
            BytesIO: A file-like object containing the generated PDF document
        """
        template_str: str = self.template.get_template_data()

        if self.template.template_type == "DEFAULT":
            template_data: dict[str, Any] = DefaultTemplateData(
                self.cmdb_render_object,
                template_str,
                self.request_user,
                self.template.template_type,
            ).get_template_data()
        else:
            template_data: dict[str, Any] = ObjectTemplateData(
                self.cmdb_render_object,
                self.objects_manager,
                self.request_user,
                self.template.template_type
            ).get_template_data()


        author: str | None = None
        author_data: dict[str, Any] = self.objects_manager.get_one_from_other_collection(
            CmdbUser.COLLECTION,
            self.template.get_author_id()
        )

        if author_data:
            author_instance: CmdbUser = CmdbUser.from_data(author_data)
            author = author_instance.get_display_name()

        # Set additional Keys
        template_data['author'] = author or "unknown"
        template_data['template_label'] = self.template.get_label()
        template_data['user_display_name'] = self.request_user.get_display_name()
        template_data['current_time'] = datetime.now().strftime("%d.%m.%Y %H:%M")
        template_data['new_page'] = "<pdf:nextpage />"
        template_data['current_page_count'] = "<pdf:pagenumber />"
        template_data['total_page_count'] = "<pdf:pagecount />"

        cover_page: CoverPage = CoverPage(self.template.get_cover_page())
        toc: TableOfContents = TableOfContents(self.template.get_table_of_contents())
        page_header_footer: PageHeaderFooter = PageHeaderFooter(
            self.template.get_header(),
            self.template.get_footer(),
            self.template.get_page_config()
        )

        final_css: str = (
            self.default_css
            + page_header_footer.get_css()
            + cover_page.get_css()
            + toc.get_css()
        )

        # Add cover page, header, footer and toc to html if they are activated
        improved_template_str: str = (
            page_header_footer.get_html()
            + cover_page.get_html()
            + toc.get_html()
            + "<div>"
            + self.template.get_template_data()
            + "</div>"
        )

        # LOGGER.debug(f"template style: {self.template.get_template_style()}")
        # LOGGER.debug(f"css:\n {final_css}")
        # LOGGER.debug(f"html:\n {improved_template_str}")

        rendered_template: str = TemplateEngine().render_template_string(
            improved_template_str,
            template_data
        )

        # Construct the full HTML document
        html: str = (
            f"<html>"
            f"<head>"
            f'<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />'
            f'<meta charset="UTF-8" />'
            f'<title>{self.template.get_label()}</title>'
            f'<style>{final_css}{self.template.get_template_style()}</style>'
            f"</head>"
            f"<body>"
            f"{rendered_template}"
            f"</body>"
            f"</html>"
        )

        # Generate and return the final document
        return self.doctype.create_doc(html)
