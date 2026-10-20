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
Unit tests for cmdb.framework.rendering.render_list.RenderList

Pure tests: CmdbMultiRender is replaced at the module path, so what is pinned is the list's own part -
what it hands the renderer, and the two shapes it answers
"""
from unittest.mock import Mock, patch

import pytest

from cmdb.framework.rendering import render_list as render_list_module
from cmdb.framework.rendering.render_list import RenderList
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

SUMMARY_LINE: str = 'Rendered #1'


@pytest.fixture(name='rendered')
def fixture_rendered() -> RenderResult:
    """One render result as the renderer would answer it."""
    result = RenderResult()
    result.summary_line = SUMMARY_LINE

    return result


def _render_list(rendered: RenderResult, ref_render: bool = False):
    """A RenderList over two mock objects, with the renderer patched to answer `rendered`; answers both."""
    objects: list[Mock] = [Mock(name='first'), Mock(name='second')]
    user = Mock(name='user')
    renderer = Mock(name='CmdbMultiRender')
    renderer.return_value.result.return_value = [rendered]

    return RenderList(objects, user, ref_render), renderer, objects, user


class TestRenderResultList:
    """render_result_list() delegates to the renderer and answers one of two shapes."""

    def test_the_renderer_gets_the_objects_the_user_and_the_flag(self, rendered: RenderResult) -> None:
        """Everything the list was built with is handed on unchanged"""
        render_list, renderer, objects, user = _render_list(rendered, ref_render=True)

        with patch.object(render_list_module, 'CmdbMultiRender', renderer):
            render_list.render_result_list()

        renderer.assert_called_once_with(objects, user, True)

    def test_the_results_are_answered_as_they_are(self, rendered: RenderResult) -> None:
        """Without raw, the RenderResults themselves"""
        render_list, renderer, _objects, _user = _render_list(rendered)

        with patch.object(render_list_module, 'CmdbMultiRender', renderer):
            assert render_list.render_result_list() == [rendered]

    def test_raw_answers_each_results_attribute_dict(self, rendered: RenderResult) -> None:
        """With raw, one plain dict per result - what the object listing serialises"""
        render_list, renderer, _objects, _user = _render_list(rendered)

        with patch.object(render_list_module, 'CmdbMultiRender', renderer):
            raw = render_list.render_result_list(raw=True)

        assert raw == [vars(rendered)]
        assert raw[0]['render_problems'] == []

    def test_reference_rendering_is_off_by_default(self, rendered: RenderResult) -> None:
        """A list built without the flag renders without resolving references"""
        render_list, renderer, objects, user = _render_list(rendered)

        with patch.object(render_list_module, 'CmdbMultiRender', renderer):
            render_list.render_result_list()

        renderer.assert_called_once_with(objects, user, False)
