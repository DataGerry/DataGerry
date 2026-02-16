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
"""
from logging import Logger, getLogger

from io import BytesIO
from xhtml2pdf import pisa
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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
        which acts as an in-memory file-like object containing the PDF data.

        Args:
            input_data (str): The HTML content to be converted into a PDF.

        Returns:
            BytesIO: A file-like object containing the generated PDF data
        """
        output = BytesIO()

        pisa.CreatePDF(input_data, dest=output, encoding='utf8')

        # Reset the cursor to the beginning of the BytesIO object before returning
        output.seek(0)

        return output
