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
Implementation of PdfDocumentType for DocapiTemplates

**A document loads no resource from outside itself.** The HTML converted here is author-controlled (the template's
markup and style), and xhtml2pdf on its own resolves every resource that markup names - a URL it fetches from the
server, a path it reads from the server's disk. Every load goes through `pdf_resource_link_callback`, which lets only
inline ``data:`` URIs through and replaces anything else with an empty resource, logged. So rendering a template never
makes the server send a request or read a file, and a slow host can not hold the worker
"""
from logging import Logger, getLogger
from typing import Any

from io import BytesIO
from xhtml2pdf import pisa

from cmdb.models.docapi_model.docapi_pdf_constants import ALLOWED_RESOURCE_PREFIX, REFUSED_RESOURCE_URI
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# How long a refused reference may be in the log line - the whole of one could be a long inline value
LOGGED_URI_MAX_LENGTH: int = 200


def pdf_resource_link_callback(uri: Any, _relative: Any = None) -> str | None:
    """
    Decides what a resource the converted HTML names may load - xhtml2pdf's ``link_callback``

    An inline ``data:`` URI is the document's own content and loads as it is. Anything else a template names - an
    ``http(s)`` URL, a ``file:`` URL, a bare path - is refused: answered with `REFUSED_RESOURCE_URI`, an empty inline
    resource, and logged. A value that is no string is xhtml2pdf's own internal data, never the template's, and is
    left as it is

    Args:
        uri (Any): The reference as the markup or style names it
        _relative (Any): The base it would be resolved against - unused, nothing is resolved

    Returns:
        str | None: The reference to load; None leaves an internal (non-string) value unchanged
    """
    if not isinstance(uri, str):
        return None

    if uri.startswith(ALLOWED_RESOURCE_PREFIX):
        return uri

    LOGGER.warning("[PdfDocumentType] A document referred to a resource outside itself - left out: %.*s",
                   LOGGED_URI_MAX_LENGTH, uri)

    return REFUSED_RESOURCE_URI

# -------------------------------------------------------------------------------------------------------------------- #
#                                                PdfDocumentType - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class PdfDocumentType:
    """
    A class that represents a PDF document type
    """
    FILE_EXTENSION  = "pdf"
    ICON = "file-pdf"
    LABEL = "PDF"


    def create_doc(self, input_data: str) -> BytesIO:
        """
        Creates a PDF document from the given input data (HTML string)

        This method uses the `xhtml2pdf` library to convert the provided HTML input
        into a PDF document. The resulting PDF is returned as a `BytesIO` object,
        which acts as an in-memory file-like object containing the PDF data. Every resource the HTML names goes
        through `pdf_resource_link_callback`: only inline ``data:`` URIs load, nothing is fetched or read

        Args:
            input_data (str): The HTML content to be converted into a PDF.

        Returns:
            BytesIO: A file-like object containing the generated PDF data
        """
        output = BytesIO()

        pisa.CreatePDF(input_data, dest=output, encoding='utf8', link_callback=pdf_resource_link_callback)

        # Reset the cursor to the beginning of the BytesIO object before returning
        output.seek(0)

        return output
