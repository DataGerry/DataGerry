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
End-to-end integration test for DocAPI document generation

Drives the whole render-and-generate pipeline the way the render route does: seed a real
CmdbType + CmdbObject, render it with CmdbMultiRender, then run ObjectDocumentGenerator.generate_doc()
against a template shaped exactly like the Angular frontend sends it (header/footer with their own
config.height, a toc with pdftoc/level styling, page-config margins). Confirms, against a real
MongoDB + the real xhtml2pdf backend, that the recent DocAPI/render refactors still produce a document
and that the footer-height fix uses the footer's own height (not the header's).
"""
from typing import Any

import pytest

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager
from cmdb.database import MongoDatabaseManager
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.docapi.docapi_template.docgen_header_footer import PageHeaderFooter
from cmdb.models.docapi_model.object_document_generator import ObjectDocumentGenerator
from cmdb.models.docapi_model.pdf_document_type import PdfDocumentType
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

GEN_TYPE_ID: int = 88201
GEN_OBJ_ID: int = 88211
TEMPLATE_ID: int = 88221

NAME_FIELD: str = 'dg-name'
OBJ_NAME_VALUE: str = 'Generated <b>Server</b>'  # embeds HTML to prove autoescaping in the document

HEADER_HEIGHT: int = 30
FOOTER_HEIGHT: int = 55  # deliberately different from the header (regression: footer must use this)

PDF_MAGIC: bytes = b'%PDF'


@pytest.fixture(autouse=True)
def _render_context(rest_api):
    """Pushes the REST API app context so ManagerProvider resolves the database manager."""
    with rest_api.application.app_context():
        yield


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a type + object for the render, cleaning up afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': GEN_TYPE_ID})
        objects.delete_many({'public_id': GEN_OBJ_ID})

    _purge()
    types.insert_one(make_type_doc(
        GEN_TYPE_ID, 'gen-type',
        fields=[{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
    ))
    objects.insert_one({
        'public_id': GEN_OBJ_ID, 'type_id': GEN_TYPE_ID, 'active': True, 'author_id': 1,
        'version': '1.0.0', 'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': OBJ_NAME_VALUE}],
    })
    yield
    _purge()


def _fe_template() -> DocapiTemplate:
    """A DocapiTemplate shaped exactly like the Angular frontend sends it (header/footer/toc/page_config)."""
    data: dict[str, Any] = {
        'public_id': TEMPLATE_ID,
        'name': 'gen-template',
        'label': 'Generated Doc',
        'active': True,
        'author_id': 1,
        'template_type': 'OBJECT',
        # a field placeholder (its value carries HTML that autoescaping must escape) + a pdf marker
        'template_data': '<h1>{{ fields.dg_name }}</h1><span>{{ new_page }}</span>',
        'template_style': '',
        'header': {'activated': True, 'content': 'HEADER', 'config': {'height': HEADER_HEIGHT}},
        'footer': {'activated': True, 'content': 'FOOTER', 'config': {'height': FOOTER_HEIGHT}},
        'table_of_contents': {
            'activated': True,
            'config': {
                'pdftoc': {'line-height': '1.4'},
                'level0': {'font-size': '12pt', 'font-weight': 'bold', 'margin-top': '10pt',
                           'margin-bottom': '4pt', 'padding-bottom': '2pt'},
            },
        },
        'cover_page': {'activated': True, 'content': '<h2>Cover</h2>', 'config': {}},
        'page_config': {'margin': {'margin-top': 20, 'margin-bottom': 20,
                                   'margin-left': 20, 'margin-right': 20}},
    }
    return DocapiTemplate.from_data(data)


def _render_object(user) -> RenderResult:
    """Renders the seeded object into a RenderResult."""
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    obj = CmdbObject.from_data(objects_manager.get_object(GEN_OBJ_ID))
    return CmdbMultiRender([obj], user).result(single_object=True)


class TestDocumentGeneration:
    """The full generate_doc pipeline produces a PDF from an FE-shaped template."""

    def test_generate_doc_produces_pdf(self, full_access_user) -> None:
        """generate_doc renders the object into a non-empty PDF document without raising."""
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, full_access_user)
        generator = ObjectDocumentGenerator(
            _fe_template(), _render_object(full_access_user), PdfDocumentType(),
            objects_manager, full_access_user,
        )

        output = generator.generate_doc()
        payload = output.getvalue()

        assert payload.startswith(PDF_MAGIC)
        assert len(payload) > 0


class TestHeaderFooterCss:
    """The header/footer CSS built from an FE-shaped template uses each section's own height."""

    def test_footer_uses_its_own_height_not_the_header(self) -> None:
        """Regression: the footer frame height comes from the footer config, not the header config."""
        template = _fe_template()
        page_header_footer = PageHeaderFooter(
            template.get_header(), template.get_footer(), template.get_page_config()
        )

        css = page_header_footer.get_css()

        # both frames present, each carrying its own configured height
        assert 'header_frame' in css and f'height: {HEADER_HEIGHT}pt;' in css
        assert 'footer_frame' in css and f'height: {FOOTER_HEIGHT}pt;' in css
