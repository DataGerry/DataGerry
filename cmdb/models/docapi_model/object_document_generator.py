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
from html import escape
from logging import Logger, getLogger
from typing import Any
from io import BytesIO
from datetime import datetime

from markupsafe import Markup

from cmdb.manager import ObjectsManager

from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.docapi.docapi_template.docgen_cover_page import CoverPage
from cmdb.framework.docapi.docapi_template.docgen_toc import TableOfContents
from cmdb.framework.docapi.docapi_template.docgen_header_footer import PageHeaderFooter
from cmdb.models.docapi_model.template_engine import TemplateEngine
from cmdb.models.docapi_model.pdf_document_type import PdfDocumentType
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
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
    # Fallback shown when no display name is available
    UNKNOWN_DISPLAY_NAME: str = "unknown"
    # strftime format for the document's generation timestamp
    DATETIME_FORMAT: str = "%d.%m.%Y %H:%M"
    # xhtml2pdf page markers injected as template variables
    PDF_NEW_PAGE: str = "<pdf:nextpage />"
    PDF_CURRENT_PAGE: str = "<pdf:pagenumber />"
    PDF_TOTAL_PAGES: str = "<pdf:pagecount />"

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
        request_user: CmdbUser | None = None
        ) -> None:
        """
        Initializes the ObjectDocumentGenerator

        Args:
            template (DocapiTemplate): The template object containing structure and styling
            cmdb_render_object (RenderResult): The CmdbObject RenderResult
            doctype (PdfDocumentType): The document type that determines the final output format
            objects_manager (ObjectsManager): The manager responsible for CmdbObject operations
            request_user (CmdbUser | None): The user requesting the document (optional)
        """
        self.template: DocapiTemplate = template
        self.cmdb_render_object: RenderResult = cmdb_render_object
        self.doctype: PdfDocumentType = doctype
        self.objects_manager: ObjectsManager = objects_manager
        self.request_user: CmdbUser | None = request_user


    def generate_doc(self) -> BytesIO:
        """
        Generates a document by rendering the template with CmdbObject data

        The method fetches relevant data, applies it to the template, constructs an HTML document,
        and then generates the final document

        Returns:
            BytesIO: A file-like object containing the generated PDF document
        """
        template_str: str = self.template.get_template_data()

        template_data: dict[str, Any] = self._build_template_data(template_str)
        template_data.update(self._build_meta_keys())

        cover_page: CoverPage = CoverPage(self.template.get_cover_page())
        toc: TableOfContents = TableOfContents(self.template.get_table_of_contents())
        page_header_footer: PageHeaderFooter = PageHeaderFooter(
            self.template.get_header(),
            self.template.get_footer(),
            self.template.get_page_config()
        )

        final_css: str = self._build_css(cover_page, toc, page_header_footer)

        # Add cover page, header, footer and toc to html if they are activated
        improved_template_str: str = (
            page_header_footer.get_html()
            + cover_page.get_html()
            + toc.get_html()
            + "<div>"
            + template_str
            + "</div>"
        )

        rendered_template: str = TemplateEngine.render_template_string(improved_template_str, template_data)

        document: str = self._build_html(rendered_template, final_css)

        return self.doctype.create_doc(document)


    def _build_template_data(self, template_str: str) -> dict[str, Any]:
        """
        Builds the base template data for the object, choosing the renderer by template type

        Args:
            template_str (str): The raw template body (needed by the DEFAULT renderer)

        Returns:
            dict[str, Any]: The template data produced by the matching template-data builder
        """
        if self.template.template_type == DocapiTemplateType.DEFAULT:
            return DefaultTemplateData(
                self.cmdb_render_object,
                template_str,
                self.request_user,
                self.template.template_type,
            ).get_template_data()

        return ObjectTemplateData(
            self.cmdb_render_object,
            self.objects_manager,
            self.request_user,
            self.template.template_type
        ).get_template_data()


    def _resolve_author(self) -> str:
        """
        Resolves the template author's display name

        Returns:
            str: The author's display name, or ``UNKNOWN_DISPLAY_NAME`` if the author is not found
        """
        author_data: dict[str, Any] = self.objects_manager.get_one_from_other_collection(
            CmdbUser.COLLECTION,
            self.template.get_author_id()
        )

        if author_data:
            return CmdbUser.from_data(author_data).get_display_name() or self.UNKNOWN_DISPLAY_NAME

        return self.UNKNOWN_DISPLAY_NAME


    def _build_meta_keys(self) -> dict[str, Any]:
        """
        Builds the document-level template keys (author, labels, timestamp and PDF page markers)

        Returns:
            dict[str, Any]: The additional keys merged into the template data
        """
        user_display_name: str = (
            self.request_user.get_display_name() if self.request_user else self.UNKNOWN_DISPLAY_NAME
        )

        return {
            'author': self._resolve_author(),
            'template_label': self.template.get_label(),
            'user_display_name': user_display_name,
            'current_time': datetime.now().strftime(self.DATETIME_FORMAT),
            # Trusted xhtml2pdf markup — mark safe so the autoescaping engine emits it verbatim
            'new_page': Markup(self.PDF_NEW_PAGE),
            'current_page_count': Markup(self.PDF_CURRENT_PAGE),
            'total_page_count': Markup(self.PDF_TOTAL_PAGES),
        }


    def _build_css(self, cover_page: CoverPage, toc: TableOfContents, page_header_footer: PageHeaderFooter) -> str:
        """
        Concatenates the default CSS with the per-component CSS

        Args:
            cover_page (CoverPage): The cover page component
            toc (TableOfContents): The table-of-contents component
            page_header_footer (PageHeaderFooter): The header/footer component

        Returns:
            str: The combined CSS for the document
        """
        return (
            self.default_css
            + page_header_footer.get_css()
            + cover_page.get_css()
            + toc.get_css()
        )


    def _build_html(self, body: str, css: str) -> str:
        """
        Wraps the rendered body and CSS into a full HTML document

        Args:
            body (str): The rendered template body
            css (str): The combined document CSS

        Returns:
            str: The full HTML document string
        """
        return (
            "<html>"
            "<head>"
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />'
            '<meta charset="UTF-8" />'
            f'<title>{escape(self.template.get_label())}</title>'
            f'<style>{css}{self.template.get_template_style()}</style>'
            "</head>"
            "<body>"
            f"{body}"
            "</body>"
            "</html>"
        )
