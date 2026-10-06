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
What a generated document shows of the references its object holds - end to end, through the render route

`GET /docapi/template/<id>/render/<object_id>` renders the object with its references resolved through the
caller's READ ACL, so a template reads into a plain reference, its next hop, a reference section and
`object(<id>)`'s references; a location field shows its location's name, whatever the field is called. Checked
twice: on the HTML the template engine produced, and on the text of the PDF that came back - so both the data and
the generated document are what the reader gets. For the admin group, and for the default user group, which may
not read HIDDEN
"""
import re
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest
from pypdf import PdfReader

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.template_engine import TemplateEngine
from tests.utils import docapi_reference_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

RENDER_URL: str = '/docapi/template/{template_id}/render/{object_id}'
PDF_MAGIC: bytes = b'%PDF'
# The hidden reference's marker with nothing - or only whitespace, a non-breaking space included - inside
BLANK_HIDDEN: str = r'HIDDEN\[\s*\]'

# What both template types show: (marker, value)
SHARED_EXPECTED: list[tuple[str, str]] = [
    ('ROOT', seed.ROOT_VALUE),
    ('HOP1', seed.MID_VALUE),
    ('HOP2', seed.LEAF_VALUE),
    ('SECTION', seed.MID_VALUE),
    ('PLACE', seed.LOCATION_NAME),
]
DEFAULT_ONLY_EXPECTED: list[tuple[str, str]] = [
    ('HIDDEN', seed.HIDDEN_VALUE),
    ('OBJECT', seed.LEAF_VALUE),
]
TEMPLATES: list[Any] = [
    pytest.param(seed.DEFAULT_TEMPLATE_ID, SHARED_EXPECTED + DEFAULT_ONLY_EXPECTED, id='default-template'),
    pytest.param(seed.OBJECT_TEMPLATE_ID, SHARED_EXPECTED, id='object-template'),
]


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The document generator is licensed, so the render answers its data rather than its licence gate."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the reference fixture for each test and removes it after."""
    seed.seed(database_manager, database_name)
    yield
    seed.purge(database_manager, database_name)


@pytest.fixture(name='rendered_html')
def fixture_rendered_html(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captures every HTML body the template engine produces, before it is turned into a PDF."""
    captured: list[str] = []
    original = TemplateEngine.render_template_string

    def _capturing(template_str: str, data: dict[str, Any]) -> str:
        html: str = original(template_str, data)
        captured.append(html)
        return html

    monkeypatch.setattr(TemplateEngine, 'render_template_string', staticmethod(_capturing))

    return captured


def _render(rest_api, template_id: int, **kwargs: Any):
    """Renders `template_id` for ROOT."""
    return rest_api.get(RENDER_URL.format(template_id=template_id, object_id=seed.ROOT_ID), **kwargs)


def _pdf_text(response: Any) -> str:
    """The text of every page of the PDF the route answered, whitespace collapsed."""
    reader = PdfReader(BytesIO(response.data))

    return ' '.join(' '.join((page.extract_text() or '').split()) for page in reader.pages)


class TestTheDocumentTheAdminGets:
    """Every reference resolves: the admin group may read everything."""

    @pytest.mark.parametrize('template_id, expected', TEMPLATES)
    def test_the_route_answers_a_pdf(self, rest_api, template_id: int, expected: list[tuple[str, str]]) -> None:
        """The generator still produces a document"""
        del expected
        response = _render(rest_api, template_id)

        assert response.status_code == HTTPStatus.OK
        assert response.data.startswith(PDF_MAGIC)

    @pytest.mark.parametrize('template_id, expected', TEMPLATES)
    def test_the_template_engine_gets_every_value(self, rest_api, rendered_html: list[str], template_id: int,
                                                  expected: list[tuple[str, str]]) -> None:
        """Check one: the HTML the template produced"""
        _render(rest_api, template_id)

        assert rendered_html
        for marker, value in expected:
            assert seed.marked(marker, value) in rendered_html[-1], marker

    @pytest.mark.parametrize('template_id, expected', TEMPLATES)
    def test_the_pdf_carries_every_value(self, rest_api, template_id: int, expected: list[tuple[str, str]]) -> None:
        """Check two: the text of the generated PDF"""
        text: str = _pdf_text(_render(rest_api, template_id))

        for marker, value in expected:
            assert seed.marked(marker, value) in text, (marker, text)

    @pytest.mark.parametrize('template_id, expected', TEMPLATES)
    def test_a_location_field_is_never_read_as_an_object(self, rest_api, template_id: int,
                                                         expected: list[tuple[str, str]]) -> None:
        """The decoy object shares the location node's id: its value appears nowhere"""
        del expected
        assert seed.DECOY_VALUE not in _pdf_text(_render(rest_api, template_id))


class TestTheDocumentTheDefaultUserGets:
    """The default user group may not read HIDDEN: its reference renders blank, everything else resolves."""

    def test_the_hidden_reference_is_blank_in_the_html(self, rest_api, rendered_html: list[str]) -> None:
        """Blank, exactly like an unset reference - and the readable hops still resolve"""
        _render(rest_api, seed.DEFAULT_TEMPLATE_ID, user=seed.default_user())

        # A blank renders as a non-breaking space, as every unset value does
        assert re.search(BLANK_HIDDEN, rendered_html[-1])
        assert seed.HIDDEN_VALUE not in rendered_html[-1]
        assert seed.marked('HOP2', seed.LEAF_VALUE) in rendered_html[-1]

    def test_the_hidden_value_is_not_in_the_pdf(self, rest_api) -> None:
        """Nor in the document that came back"""
        response = _render(rest_api, seed.DEFAULT_TEMPLATE_ID, user=seed.default_user())

        assert response.status_code == HTTPStatus.OK
        text: str = _pdf_text(response)
        assert seed.HIDDEN_VALUE not in text
        assert seed.marked('HOP1', seed.MID_VALUE) in text


class TestAFrontendShapedDocument:
    """The whole generator - cover page, table of contents, header, footer, page margins - around the references."""

    TEMPLATE_ID: int = 89623
    COVER: str = 'docref-cover-page'
    HEADER: str = 'docref-header'
    FOOTER: str = 'docref-footer'

    @pytest.fixture(autouse=True)
    def _template(self, database_manager: MongoDatabaseManager, database_name: str):
        """A DEFAULT template shaped exactly like the Angular frontend sends it, reading every reference"""
        templates = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        templates.delete_many({'public_id': self.TEMPLATE_ID})
        templates.insert_one({
            'public_id': self.TEMPLATE_ID, 'name': 'docref-fe', 'label': 'Doc refs FE', 'active': True,
            'author_id': 1, 'template_type': DocapiTemplateType.DEFAULT.value, 'template_style': '',
            'template_data': f'<h1>Body</h1>{seed.DEFAULT_TEMPLATE_BODY}<span>{{{{ new_page }}}}</span>',
            'header': {'activated': True, 'content': self.HEADER, 'config': {'height': 30}},
            'footer': {'activated': True, 'content': self.FOOTER, 'config': {'height': 55}},
            'table_of_contents': {'activated': True, 'config': {
                'pdftoc': {'line-height': '1.4'},
                'level0': {'font-size': '12pt', 'font-weight': 'bold', 'margin-top': '10pt',
                           'margin-bottom': '4pt', 'padding-bottom': '2pt'},
            }},
            'cover_page': {'activated': True, 'content': f'<h2>{self.COVER}</h2>', 'config': {}},
            'page_config': {'margin': {'margin-top': 20, 'margin-bottom': 20, 'margin-left': 20,
                                       'margin-right': 20}},
        })
        yield
        templates.delete_many({'public_id': self.TEMPLATE_ID})

    def test_the_document_has_every_part_and_every_value(self, rest_api) -> None:
        """Cover, header, footer and the body's values, in the PDF that came back"""
        response = _render(rest_api, self.TEMPLATE_ID)

        assert response.status_code == HTTPStatus.OK
        assert response.data.startswith(PDF_MAGIC)
        text: str = _pdf_text(response)
        for part in (self.COVER, self.HEADER, self.FOOTER):
            assert part in text, part
        for marker, value in SHARED_EXPECTED + DEFAULT_ONLY_EXPECTED:
            assert seed.marked(marker, value) in text, (marker, text)

    def test_the_document_has_more_than_one_page(self, rest_api) -> None:
        """The cover page and the page break are still applied"""
        assert len(PdfReader(BytesIO(_render(rest_api, self.TEMPLATE_ID).data)).pages) > 1
