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
Integration tests for the cost of a DocAPI document's references, against a real MongoDB

Driven through the real `DocApiRenderer`, on a tree of references three hops deep (1 + 3 + 9 + 27 objects) and on a
cycle. What is checked: every object is rendered once, the document needs one render per level rather than one per
reference, no object is read one by one - and the deepest value still reaches the template
"""
from collections import Counter
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.docapi_model.docapi_reference_constants import DEFAULT_REFERENCE_DEPTH
from cmdb.models.docapi_model.docapi_renderer import DocApiRenderer
from cmdb.models.docapi_model.template_engine import TemplateEngine
from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from tests.utils import docapi_fanout_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

FIELDS: str = 'fields'


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the fan-out fixture and pushes the request context ManagerProvider resolves through."""
    seed.seed(database_manager, database_name)

    with rest_api.application.test_request_context():
        yield

    seed.purge(database_manager, database_name)


@pytest.fixture(name='renders')
def fixture_renders(monkeypatch: pytest.MonkeyPatch) -> list[list[int]]:
    """Records the ids every CmdbMultiRender is built for"""
    built: list[list[int]] = []
    original = CmdbMultiRender.__init__

    def _recording(self, to_render_objects, *args, **kwargs) -> None:
        built.append([obj.public_id for obj in to_render_objects])
        original(self, to_render_objects, *args, **kwargs)

    monkeypatch.setattr(CmdbMultiRender, '__init__', _recording)

    return built


@pytest.fixture(name='single_reads')
def fixture_single_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Records every one-object read"""
    reads: list[int] = []
    original = ObjectsManager.get_object

    def _recording(self, public_id, *args, **kwargs) -> Any:
        reads.append(public_id)
        return original(self, public_id, *args, **kwargs)

    monkeypatch.setattr(ObjectsManager, 'get_object', _recording)

    return reads


@pytest.fixture(name='template_input')
def fixture_template_input(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Captures the data the template engine is handed."""
    captured: list[dict[str, Any]] = []
    original = TemplateEngine.render_template_string

    def _capturing(template_str: str, data: dict[str, Any]) -> str:
        captured.append(data)
        return original(template_str, data)

    monkeypatch.setattr(TemplateEngine, 'render_template_string', staticmethod(_capturing))

    return captured


def _generate(database_manager: MongoDatabaseManager, database_name: str, root_id: int) -> None:
    """Renders `root_id` with the fan-out template for the admin, the way the render route does"""
    user: CmdbUser = CmdbUser.from_data(
        database_manager.get_collection(CmdbUser.COLLECTION, database_name).find_one({'public_id': 1}))
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    template = DocapiTemplate.from_data(database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
                                        .find_one({'public_id': seed.TEMPLATE_ID}))
    root = CmdbObject.from_data(
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': root_id}))

    DocApiRenderer(objects_manager, template, root).render_object_template(user)


class TestATreeOfReferences:
    """1 + 3 + 9 + 27 objects: one render per level."""

    def test_one_render_per_level(self, database_manager, database_name, renders: list[list[int]]) -> None:
        """The root, then each hop in one render - 4, where one render per reference made 40"""
        _generate(database_manager, database_name, seed.ROOT_ID)

        assert [sorted(batch) for batch in renders] == seed.tree_levels()
        assert len(renders) == 1 + DEFAULT_REFERENCE_DEPTH

    def test_every_object_is_rendered_once(self, database_manager, database_name, renders: list[list[int]]) -> None:
        """No object twice, none left out"""
        _generate(database_manager, database_name, seed.ROOT_ID)

        counted = Counter(public_id for batch in renders for public_id in batch)

        assert set(counted) == {public_id for level in seed.tree_levels() for public_id in level}
        assert set(counted.values()) == {1}

    def test_no_object_is_read_on_its_own(self, database_manager, database_name, single_reads: list[int]) -> None:
        """The prefetch of each level loads the next - nothing is read one by one"""
        _generate(database_manager, database_name, seed.ROOT_ID)

        assert not single_reads

    def test_the_deepest_value_reaches_the_template(
            self, database_manager, database_name, template_input: list[dict[str, Any]]) -> None:
        """Three hops down the last reference, the leaf's name - the data is what it was"""
        _generate(database_manager, database_name, seed.ROOT_ID)

        value: Any = template_input[0]
        for _ in range(DEFAULT_REFERENCE_DEPTH):
            value = value[FIELDS][seed.LAST_REFERENCE]

        assert value[FIELDS][seed.NAME_FIELD] == seed.name_of(seed.deepest_id())


class TestACycle:
    """A references B, B references A: each rendered once, the hops still resolve."""

    def test_two_objects_two_renders(self, database_manager, database_name, renders: list[list[int]]) -> None:
        """A, then B - A is not rendered again when B leads back to it"""
        _generate(database_manager, database_name, seed.CYCLE_A_ID)

        assert renders == [[seed.CYCLE_A_ID], [seed.CYCLE_B_ID]]

    def test_the_hops_alternate(
            self, database_manager, database_name, template_input: list[dict[str, Any]]) -> None:
        """A -> B -> A -> B, as far as the depth reaches"""
        _generate(database_manager, database_name, seed.CYCLE_A_ID)

        first_reference: str = seed.REFERENCE_FIELDS[0]
        hop_b = template_input[0][FIELDS][first_reference]
        hop_a = hop_b[FIELDS][first_reference]

        assert hop_b['public_id'] == seed.CYCLE_B_ID
        assert hop_a['public_id'] == seed.CYCLE_A_ID
        assert hop_a[FIELDS][first_reference]['public_id'] == seed.CYCLE_B_ID
