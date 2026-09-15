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
Unit tests for cmdb.models.docapi_model.object_document_generator.ObjectDocumentGenerator

Covers the decomposed pure helpers (_build_css, _build_html, _resolve_author, _build_meta_keys,
_build_template_data) with lightweight mocks, and the generate_doc orchestration with its
collaborators patched. No app context / database.
"""
from unittest.mock import Mock, patch

from markupsafe import Markup

from cmdb.models.docapi_model.object_document_generator import ObjectDocumentGenerator
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.object_document_generator'


def _make_generator(template=None, objects_manager=None, request_user=None, doctype=None) -> ObjectDocumentGenerator:
    """Builds an ObjectDocumentGenerator with lightweight mock collaborators."""
    return ObjectDocumentGenerator(
        template=template or Mock(),
        cmdb_render_object=Mock(),
        doctype=doctype or Mock(),
        objects_manager=objects_manager or Mock(),
        request_user=request_user,
    )


class TestBuildCss:
    """_build_css concatenates the default CSS with each component's CSS in order."""

    def test_concatenates_default_and_component_css(self) -> None:
        """The result is default_css + header/footer + cover + toc CSS, in that order."""
        cover, toc, phf = Mock(), Mock(), Mock()
        cover.get_css.return_value = 'C'
        toc.get_css.return_value = 'T'
        phf.get_css.return_value = 'H'
        gen = _make_generator()

        assert gen._build_css(cover, toc, phf) == gen.default_css + 'H' + 'C' + 'T'


class TestBuildHtml:
    """_build_html wraps body + CSS into a full document with an escaped title."""

    def test_wraps_body_and_css_with_escaped_title(self) -> None:
        """The title is HTML-escaped and the body/CSS are placed in the document."""
        template = Mock()
        template.get_label.return_value = 'R&D <Report>'
        template.get_template_style.return_value = 'body{}'
        gen = _make_generator(template=template)

        html = gen._build_html('BODY', 'CSS')

        assert '<title>R&amp;D &lt;Report&gt;</title>' in html
        assert '<style>CSSbody{}</style>' in html
        assert '<body>BODY</body>' in html
        assert html.startswith('<html>') and html.endswith('</html>')


class TestResolveAuthor:
    """_resolve_author returns the author's display name or the unknown fallback."""

    @patch(f'{MODULE}.CmdbUser')
    def test_returns_display_name_when_found(self, mock_user: Mock) -> None:
        """A found author yields its display name."""
        mock_user.from_data.return_value.get_display_name.return_value = 'Alice'
        objects_manager = Mock()
        objects_manager.get_one_from_other_collection.return_value = {'public_id': 1}
        gen = _make_generator(objects_manager=objects_manager)

        assert gen._resolve_author() == 'Alice'

    @patch(f'{MODULE}.CmdbUser')
    def test_returns_unknown_when_author_missing(self, mock_user: Mock) -> None:
        """A missing author yields the unknown fallback."""
        objects_manager = Mock()
        objects_manager.get_one_from_other_collection.return_value = None
        gen = _make_generator(objects_manager=objects_manager)

        assert gen._resolve_author() == ObjectDocumentGenerator.UNKNOWN_DISPLAY_NAME

    @patch(f'{MODULE}.CmdbUser')
    def test_returns_unknown_when_display_name_empty(self, mock_user: Mock) -> None:
        """An author with an empty display name falls back to unknown."""
        mock_user.from_data.return_value.get_display_name.return_value = ''
        objects_manager = Mock()
        objects_manager.get_one_from_other_collection.return_value = {'public_id': 1}
        gen = _make_generator(objects_manager=objects_manager)

        assert gen._resolve_author() == ObjectDocumentGenerator.UNKNOWN_DISPLAY_NAME


class TestBuildMetaKeys:
    """_build_meta_keys assembles author/label/timestamp and the PDF page markers."""

    @patch(f'{MODULE}.CmdbUser')
    def test_includes_labels_and_pdf_markers(self, mock_user: Mock) -> None:
        """The meta dict carries the resolved names and the PDF marker constants."""
        mock_user.from_data.return_value.get_display_name.return_value = 'Author'
        objects_manager = Mock()
        objects_manager.get_one_from_other_collection.return_value = {'public_id': 1}
        template = Mock()
        template.get_label.return_value = 'Lbl'
        request_user = Mock()
        request_user.get_display_name.return_value = 'Requester'
        gen = _make_generator(template=template, objects_manager=objects_manager, request_user=request_user)

        meta = gen._build_meta_keys()

        assert meta['author'] == 'Author'
        assert meta['template_label'] == 'Lbl'
        assert meta['user_display_name'] == 'Requester'
        assert meta['new_page'] == ObjectDocumentGenerator.PDF_NEW_PAGE
        assert meta['current_page_count'] == ObjectDocumentGenerator.PDF_CURRENT_PAGE
        assert meta['total_page_count'] == ObjectDocumentGenerator.PDF_TOTAL_PAGES
        assert isinstance(meta['current_time'], str) and meta['current_time']

    @patch(f'{MODULE}.CmdbUser')
    def test_user_display_name_unknown_without_request_user(self, mock_user: Mock) -> None:
        """With no request user, user_display_name falls back to unknown (no AttributeError)."""
        mock_user.from_data.return_value.get_display_name.return_value = 'Author'
        objects_manager = Mock()
        objects_manager.get_one_from_other_collection.return_value = {'public_id': 1}
        gen = _make_generator(objects_manager=objects_manager, request_user=None)

        assert gen._build_meta_keys()['user_display_name'] == ObjectDocumentGenerator.UNKNOWN_DISPLAY_NAME

    @patch(f'{MODULE}.CmdbUser')
    def test_pdf_markers_are_markup(self, mock_user: Mock) -> None:
        """The PDF page markers are Markup so the autoescaping engine emits them verbatim."""
        mock_user.from_data.return_value.get_display_name.return_value = 'Author'
        objects_manager = Mock()
        objects_manager.get_one_from_other_collection.return_value = {'public_id': 1}

        meta = _make_generator(objects_manager=objects_manager)._build_meta_keys()

        assert isinstance(meta['new_page'], Markup)
        assert isinstance(meta['current_page_count'], Markup)
        assert isinstance(meta['total_page_count'], Markup)


class TestBuildTemplateData:
    """_build_template_data selects the renderer by template type (via the enum)."""

    @patch(f'{MODULE}.ObjectTemplateData')
    @patch(f'{MODULE}.DefaultTemplateData')
    def test_default_type_uses_default_template_data(self, mock_default: Mock, mock_object: Mock) -> None:
        """A DEFAULT template uses DefaultTemplateData."""
        mock_default.return_value.get_template_data.return_value = {'k': 'default'}
        template = Mock()
        template.template_type = DocapiTemplateType.DEFAULT
        gen = _make_generator(template=template)

        assert gen._build_template_data('body') == {'k': 'default'}
        mock_default.assert_called_once()
        mock_object.assert_not_called()

    @patch(f'{MODULE}.ObjectTemplateData')
    @patch(f'{MODULE}.DefaultTemplateData')
    def test_object_type_uses_object_template_data(self, mock_default: Mock, mock_object: Mock) -> None:
        """A non-DEFAULT template uses ObjectTemplateData."""
        mock_object.return_value.get_template_data.return_value = {'k': 'object'}
        template = Mock()
        template.template_type = DocapiTemplateType.OBJECT
        gen = _make_generator(template=template)

        assert gen._build_template_data('body') == {'k': 'object'}
        mock_object.assert_called_once()
        mock_default.assert_not_called()


class TestGenerateDoc:
    """generate_doc orchestrates the collaborators and returns the created document."""

    @patch(f'{MODULE}.CmdbUser')
    @patch(f'{MODULE}.TemplateEngine')
    @patch(f'{MODULE}.PageHeaderFooter')
    @patch(f'{MODULE}.TableOfContents')
    @patch(f'{MODULE}.CoverPage')
    @patch(f'{MODULE}.ObjectTemplateData')
    def test_generate_doc_wires_render_and_returns_created_doc(
        self,
        mock_object_data: Mock,
        mock_cover: Mock,
        mock_toc: Mock,
        mock_phf: Mock,
        mock_engine: Mock,
        mock_user: Mock,
    ) -> None:
        """generate_doc renders the wrapped body once and returns doctype.create_doc's output."""
        mock_object_data.return_value.get_template_data.return_value = {}
        for component in (mock_cover, mock_toc, mock_phf):
            component.return_value.get_css.return_value = ''
            component.return_value.get_html.return_value = ''
        mock_engine.render_template_string.return_value = '<p>rendered</p>'
        mock_user.from_data.return_value.get_display_name.return_value = 'Author'

        objects_manager = Mock()
        objects_manager.get_one_from_other_collection.return_value = {'public_id': 1}
        template = Mock()
        template.template_type = DocapiTemplateType.OBJECT
        template.get_template_data.return_value = 'BODY'
        template.get_label.return_value = 'L'
        template.get_template_style.return_value = ''
        doctype = Mock()
        doctype.create_doc.return_value = 'PDF_BYTES'
        request_user = Mock()
        request_user.get_display_name.return_value = 'Requester'
        gen = _make_generator(
            template=template, objects_manager=objects_manager, doctype=doctype, request_user=request_user
        )

        result = gen.generate_doc()

        assert result == 'PDF_BYTES'
        template.get_template_data.assert_called_once()  # fetched once, reused (no double call)
        rendered_input = mock_engine.render_template_string.call_args[0][0]
        assert '<div>BODY</div>' in rendered_input
        document = doctype.create_doc.call_args[0][0]
        assert '<p>rendered</p>' in document
        assert '<title>L</title>' in document
