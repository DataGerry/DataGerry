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
Unit tests for cmdb.models.docapi_model.docapi_renderer.DocApiRenderer

Pure tests: the renderer and the generator are patched. Pins that the root object is rendered for the requesting
user WITH its references resolved - without them the renderer clears every reference field's value and a
template's ``fields.<reference>`` is always empty - and that the generator is handed that render and the user
"""
from unittest.mock import MagicMock, patch

from cmdb.models.docapi_model.docapi_renderer import DocApiRenderer
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.docapi_renderer'


def _render(request_user: MagicMock) -> tuple[MagicMock, MagicMock, MagicMock, DocApiRenderer]:
    """Runs render_object_template with the renderer, the generator and the document type patched."""
    renderer = DocApiRenderer(MagicMock(name='objects_manager'), MagicMock(name='template'), MagicMock(name='target'))

    with patch(f'{MODULE}.CmdbMultiRender') as multi_render, \
         patch(f'{MODULE}.ObjectDocumentGenerator') as generator, \
         patch(f'{MODULE}.PdfDocumentType') as document_type:
        renderer.render_object_template(request_user)

    return multi_render, generator, document_type, renderer


class TestRenderObjectTemplate:
    """render_object_template."""

    def test_the_root_is_rendered_with_its_references_resolved(self) -> None:
        """ref_render=True, for the requesting user"""
        request_user = MagicMock(name='request_user')

        multi_render, _, _, renderer = _render(request_user)

        multi_render.assert_called_once_with([renderer.target_object], request_user, ref_render=True)
        multi_render.return_value.result.assert_called_once_with(single_object=True)

    def test_the_generator_gets_the_render_and_the_user(self) -> None:
        """The template, the single render result, a PDF document type, the manager and the user"""
        request_user = MagicMock(name='request_user')

        multi_render, generator, document_type, renderer = _render(request_user)

        generator.assert_called_once_with(
            renderer.target_template, multi_render.return_value.result.return_value, document_type.return_value,
            renderer.objects_manager, request_user,
        )
        generator.return_value.generate_doc.assert_called_once_with()
