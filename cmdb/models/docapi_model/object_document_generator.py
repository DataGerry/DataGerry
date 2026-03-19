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
        @page {
            size: A4; /* width_max = 595pt, height_max = 842pt*/

            /* general page margin */
            margin: 40pt; 

            @frame header_frame {
                -pdf-frame-content: header_content;
                left: 0pt;
                width: 595pt; /* full A4 width */
                top: 20pt;
                height: 20pt;
            }

            @frame content_frame {
                left: 40pt;
                width: 512pt;
                top: 40pt; /* below header */
                height: 790pt; /* space for footer */
            }

            @frame footer_frame {
                -pdf-frame-content: footer_content;
                left: 40pt;
                width: 512pt;
                top: 810pt;
                height: 25pt;
            }
        }

        pdftoc {
            font-size: 10pt;
            line-height: 1.4;
        }

        /* Level 0 (h1) */
        pdftoc.pdftoclevel0 {
            font-weight: bold;
            font-size: 12pt;
            margin-top: 10px;
            margin-bottom: 4px;
            padding-bottom: 2px;
        }

        /* Level 1 (h2) */
        pdftoc.pdftoclevel1 {
            margin-left: 12px;
            font-size: 10pt;
            margin-top: 3px;
        }

        /* Level 2 (h3) */
        pdftoc.pdftoclevel2 {
            margin-left: 24px;
            font-size: 9pt;
            font-style: italic;
            color: #444;
        }

        /* Level 3 (h4) */
        pdftoc.pdftoclevel3 {
            margin-left: 36px;
            font-size: 9pt;
            color: #555;
        }

        /* Level 4 (h5) */
        pdftoc.pdftoclevel4 {
            margin-left: 48px;
            font-size: 8pt;
            color: #666;
        }

        /* Level 5 (h6) */
        pdftoc.pdftoclevel5 {
            margin-left: 60px;
            font-size: 8pt;
            color: #777;
            font-style: italic;
        }

        /* spacing between entries */
        pdftoc + pdftoc {
            margin-top: 2px;
        }

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
        template_str = self.template.get_template_data()

        if self.template.template_type == "DEFAULT":
            template_data = DefaultTemplateData(
                self.cmdb_render_object,
                template_str,
                self.request_user,
                self.template.template_type,
            ).get_template_data()
        else:
            template_data = ObjectTemplateData(
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

        cover_page = CoverPage(self.template.cover_page)


        final_css: str = (
            self.default_css
            + cover_page.get_css()
        )

        # Add the footer div as part of the template string
        improved_template_str = (
            cover_page.get_html()
            + self.template.get_template_data()
        )

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
