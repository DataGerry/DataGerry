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
Integration tests for a reference-section chain, in the shape the type builder writes, against a real MongoDB

A's reference section pulls B's reference section, which pulls C's main section. The render answers B's
pulled-in field with the block of B's own section - C's values, under C's type - so the frontend's
ref-section component draws them instead of "No reference set". The chain is loaded one query per hop
before the render starts; nothing is rendered twice and nothing is read one object at a time
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.framework.rendering import cmdb_multi_render as render_module
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.object_model import CmdbObject
from tests.utils import reference_chain_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the chain and pushes the app context ManagerProvider resolves through."""
    seed.seed(database_manager, database_name)

    with rest_api.application.app_context():
        yield

    seed.purge(database_manager, database_name)


def _load(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> CmdbObject:
    """Reads one seeded object."""
    return CmdbObject.from_data(
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id}))


def _render(user: Any, database_manager: MongoDatabaseManager, database_name: str,
            *public_ids: int) -> list[RenderResult]:
    """A reference-resolving render of the given A objects (A_ID when none is named)."""
    objects: list[CmdbObject] = [_load(database_manager, database_name, public_id)
                                 for public_id in public_ids or (seed.A_ID,)]

    return CmdbMultiRender(objects, user, True).result()


class TestTheChain:
    """What A's render answers for the chain."""

    def test_the_far_objects_values_reach_the_render(self, full_access_user, database_manager,
                                                     database_name) -> None:
        """C's value, two blocks down"""
        block: dict[str, Any] = seed.nested_block(
            RenderResult.to_json(_render(full_access_user, database_manager, database_name)[0]))

        assert [field['value'] for field in block['fields']] == [seed.C_VALUE]

    def test_the_block_is_c_s_section(self, full_access_user, database_manager, database_name) -> None:
        """Resolved with B's 'rb' section: the block names C's type"""
        block: dict[str, Any] = seed.nested_block(
            RenderResult.to_json(_render(full_access_user, database_manager, database_name)[0]))

        assert block['type_id'] == seed.C_TYPE_ID

    def test_the_pulled_in_field_keeps_its_stored_id(self, full_access_user, database_manager,
                                                     database_name) -> None:
        """B's field still answers the C object's id as its value"""
        rendered: dict[str, Any] = RenderResult.to_json(_render(full_access_user, database_manager, database_name)[0])
        ra_field = next(field for field in rendered['fields'] if field['name'] == seed.section_field(seed.A_SECTION))
        rb_field = next(field for field in ra_field['references']['fields']
                        if field['name'] == seed.section_field(seed.B_SECTION))

        assert rb_field['value'] == seed.C_ID

    def test_the_render_reports_no_problem(self, full_access_user, database_manager, database_name) -> None:
        """A complete chain is a complete render"""
        assert _render(full_access_user, database_manager, database_name)[0].render_problems == []


class TestWhatTheChainCosts:
    """One query per hop, no second render, no single reads."""

    def test_one_query_per_hop(self, full_access_user, database_manager, database_name,
                               monkeypatch: pytest.MonkeyPatch) -> None:
        """Two A objects, one chain: B in the first query, C in the second"""
        requested: list[set[int]] = []
        original = ObjectsManager.get_objects_lookup

        def _spy(manager: ObjectsManager, public_ids: list[int], *args: Any) -> Any:
            requested.append(set(public_ids))
            return original(manager, public_ids, *args)

        monkeypatch.setattr(ObjectsManager, 'get_objects_lookup', _spy)

        _render(full_access_user, database_manager, database_name, seed.A_ID, seed.SECOND_A_ID)

        assert requested == [{seed.B_ID}, {seed.C_ID}]

    def test_no_render_is_built_for_a_chain_object(self, full_access_user, database_manager, database_name,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
        """The chain is merged - the only render is the one asked for"""
        built: list[list[int]] = []
        original = render_module.CmdbMultiRender.__init__

        def _spy(render: CmdbMultiRender, to_render_objects: list[CmdbObject], *args: Any, **kwargs: Any) -> None:
            built.append([obj.public_id for obj in to_render_objects])
            original(render, to_render_objects, *args, **kwargs)

        monkeypatch.setattr(render_module.CmdbMultiRender, '__init__', _spy)

        _render(full_access_user, database_manager, database_name)

        assert built == [[seed.A_ID]]

    def test_no_object_is_read_on_its_own(self, full_access_user, database_manager, database_name,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        """Everything came with the prefetch"""
        reads: list[Any] = []
        original = ObjectsManager.get_object

        def _spy(manager: ObjectsManager, public_id: Any, *args: Any, **kwargs: Any) -> Any:
            reads.append(public_id)
            return original(manager, public_id, *args, **kwargs)

        monkeypatch.setattr(ObjectsManager, 'get_object', _spy)

        _render(full_access_user, database_manager, database_name)

        assert not reads


class TestAChainThatEnds:
    """The far end missing, or the middle unset."""

    def test_a_far_object_that_is_gone_renders_like_an_unset_one(
            self, full_access_user, database_manager, database_name) -> None:
        """The C object deleted behind B's back: the block answers no value, and no problem (one rule at every depth)"""
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_one({'public_id': seed.C_ID})

        result: RenderResult = _render(full_access_user, database_manager, database_name)[0]

        assert [field['value'] for field in seed.nested_block(RenderResult.to_json(result))['fields']] == [None]
        assert result.render_problems == []

    def test_an_unset_middle_reference_answers_an_empty_block(
            self, full_access_user, database_manager, database_name) -> None:
        """B references nothing yet: its pulled-in field answers C's fields without values"""
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
            {'public_id': seed.B_ID, 'fields.name': seed.section_field(seed.B_SECTION)},
            {'$set': {'fields.$.value': None}},
        )

        block: dict[str, Any] = seed.nested_block(
            RenderResult.to_json(_render(full_access_user, database_manager, database_name)[0]))

        assert [field['value'] for field in block['fields']] == [None]
