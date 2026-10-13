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
Unit tests for cmdb.models.docapi_model.pdf_document_type

Pure tests: what `pdf_resource_link_callback` lets a document load - an inline ``data:`` URI as it is, every other
reference replaced by the empty inline resource and logged, xhtml2pdf's own non-string values left alone - and that
`create_doc` hands the callback to the converter. The conversion itself is the integration test's
"""
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.models.docapi_model import pdf_document_type as module
from cmdb.models.docapi_model.docapi_pdf_constants import ALLOWED_RESOURCE_PREFIX, REFUSED_RESOURCE_URI
from cmdb.models.docapi_model.pdf_document_type import (
    LOGGED_URI_MAX_LENGTH,
    PdfDocumentType,
    pdf_resource_link_callback,
)
# -------------------------------------------------------------------------------------------------------------------- #

INLINE_IMAGE: str = 'data:image/png;base64,iVBORw0KGgo='
HTML: str = '<p>x</p>'

# References a template could name that point outside the document
OUTSIDE: list[str] = [
    'http://internal.example/metadata',
    'https://example.org/logo.png',
    'file:///etc/hostname',
    '/var/lib/datagerry/logo.png',
    'logo.png',
    '//example.org/logo.png',
    'DATA:image/png;base64,iVBORw0KGgo=',
    ' data:image/png;base64,iVBORw0KGgo=',
    '',
]


class TestPdfResourceLinkCallback:
    """pdf_resource_link_callback"""

    def test_an_inline_uri_loads_as_it_is(self) -> None:
        """The document's own content"""
        assert pdf_resource_link_callback(INLINE_IMAGE, '/some/base') == INLINE_IMAGE

    @pytest.mark.parametrize('uri', OUTSIDE)
    def test_anything_else_is_replaced_by_the_empty_resource(self, uri: str) -> None:
        """A URL of any scheme, a path, an inline URI spelled differently than xhtml2pdf recognises it"""
        assert pdf_resource_link_callback(uri) == REFUSED_RESOURCE_URI

    def test_a_refusal_is_logged_shortened(self, caplog: pytest.LogCaptureFixture) -> None:
        """The reference named, at most LOGGED_URI_MAX_LENGTH characters of it"""
        long_uri: str = 'http://example.org/' + 'a' * (LOGGED_URI_MAX_LENGTH * 2)

        with caplog.at_level('WARNING'):
            pdf_resource_link_callback(long_uri)

        assert long_uri[:LOGGED_URI_MAX_LENGTH] in caplog.text
        assert long_uri[:LOGGED_URI_MAX_LENGTH + 1] not in caplog.text

    def test_an_inline_uri_is_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Nothing was refused"""
        with caplog.at_level('WARNING'):
            pdf_resource_link_callback(INLINE_IMAGE)

        assert not caplog.records

    @pytest.mark.parametrize('value', [None, b'%PDF-1.4', 7])
    def test_a_non_string_value_is_left_alone(self, value: Any) -> None:
        """xhtml2pdf's own internal data - None keeps it unchanged"""
        assert pdf_resource_link_callback(value) is None

    def test_the_refusal_is_a_well_formed_empty_inline_uri(self) -> None:
        """xhtml2pdf takes a falsy answer as 'keep the original', and refuses a malformed inline URI"""
        assert REFUSED_RESOURCE_URI.startswith(ALLOWED_RESOURCE_PREFIX)
        assert REFUSED_RESOURCE_URI.endswith('base64,')


class TestCreateDoc:
    """PdfDocumentType.create_doc"""

    def test_the_converter_gets_the_callback(self) -> None:
        """Every resource load goes through it"""
        with patch.object(module.pisa, 'CreatePDF') as create_pdf:
            PdfDocumentType().create_doc(HTML)

        assert create_pdf.call_args.kwargs['link_callback'] is pdf_resource_link_callback

    def test_the_document_is_answered_from_its_start(self) -> None:
        """A readable PDF"""
        output = PdfDocumentType().create_doc(HTML)

        assert output.tell() == 0 and output.read(5) == b'%PDF-'
