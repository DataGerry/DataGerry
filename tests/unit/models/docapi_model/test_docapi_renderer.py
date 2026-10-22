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

Pure tests: the document's resolver and the generator are patched. Pins that the root object is rendered through
one resolver started for the requesting user - it renders with references resolved; without them the renderer clears
every reference field's value and a template's ``fields.<reference>`` is always empty - and that the generator is
handed that render, the user and the same resolver
"""
from unittest.mock import MagicMock, patch

from cmdb.models.docapi_model.docapi_renderer import DocApiRenderer
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.docapi_renderer'


def _render(
        request_user: MagicMock, renders: list | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock, DocApiRenderer]:
    """Runs render_object_template with the resolver, the generator and the document type patched."""
    renderer = DocApiRenderer(MagicMock(name='objects_manager'), MagicMock(name='template'), MagicMock(name='target'))

    with patch(f'{MODULE}.DocumentReferenceResolver') as resolver, \
         patch(f'{MODULE}.ObjectDocumentGenerator') as generator, \
         patch(f'{MODULE}.PdfDocumentType') as document_type:
        resolver.return_value.render_objects.return_value = ['root_render'] if renders is None else renders
        renderer.render_object_template(request_user)

    return resolver, generator, document_type, renderer


class TestRenderObjectTemplate:
    """render_object_template."""

    def test_the_root_is_rendered_through_one_resolver_for_the_user(self) -> None:
        """Started for the requesting user and the objects manager; it renders the root alone"""
        request_user = MagicMock(name='request_user')

        resolver, _, _, renderer = _render(request_user)

        resolver.assert_called_once_with(request_user, renderer.objects_manager)
        resolver.return_value.render_objects.assert_called_once_with([renderer.target_object])

    def test_the_generator_gets_the_render_the_user_and_the_resolver(self) -> None:
        """The template, the root's render, a PDF document type, the manager, the user and the same resolver"""
        request_user = MagicMock(name='request_user')

        resolver, generator, document_type, renderer = _render(request_user)

        generator.assert_called_once_with(
            renderer.target_template, 'root_render', document_type.return_value,
            renderer.objects_manager, request_user, resolver.return_value,
        )
        generator.return_value.generate_doc.assert_called_once_with()

    def test_a_root_without_a_render_hands_none_on(self) -> None:
        """The root's type is missing - as before, the generator gets None rather than an error here"""
        _, generator, _, _ = _render(MagicMock(name='request_user'), renders=[])

        assert generator.call_args.args[1] is None
