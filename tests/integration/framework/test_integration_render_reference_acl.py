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
Integration tests for the render's READ ACL over referenced objects

A real render against a real MongoDB, for the admin group (which may read the hidden type) and for the
default user group (which may not). A reference to an object the user may not read renders exactly like
an unset one: an empty `reference`, a reference section without values, no render problem - and the
stored id stays the field's value. The denied types are read once per render, and an id a load did not
answer is not asked for again
"""
import json
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.framework.rendering import reference_read_scope as scope_module
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_constants import RenderedFieldKey, RenderedReferenceSectionKey
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_reference import TypeReference
from cmdb.models.user_model import CmdbUser
from tests.utils import reference_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the reference-ACL fixture and pushes the app context ManagerProvider resolves through."""
    seed.seed(database_manager, database_name)

    with rest_api.application.app_context():
        yield

    seed.purge(database_manager, database_name)


def _render_main(user: CmdbUser, database_manager: MongoDatabaseManager, database_name: str,
                 *public_ids: int) -> CmdbMultiRender:
    """A reference-resolving render of the given MAIN objects (MAIN_ID when none is named)."""
    objects = [seed.load(database_manager, database_name, public_id) for public_id in public_ids or (seed.MAIN_ID,)]

    return CmdbMultiRender(objects, user, True)


def _result(user: CmdbUser, database_manager: MongoDatabaseManager, database_name: str) -> RenderResult:
    """The rendered MAIN object."""
    results: list[RenderResult] = _render_main(user, database_manager, database_name).result()

    return results[0]


def _field(result: RenderResult, name: str) -> dict[str, Any]:
    """The rendered field with the given name."""
    return next(field for field in result.fields if field[FieldKey.NAME] == name)


def _section_values(result: RenderResult, section_name: str) -> list[Any]:
    """The values a reference section's pulled-in fields answer."""
    references: dict[str, Any] = _field(result, seed.section_field(section_name))[RenderedFieldKey.REFERENCES]

    return [field[FieldKey.VALUE] for field in references[RenderedReferenceSectionKey.FIELDS]]


def _as_text(result: RenderResult) -> str:
    """The whole rendered object as the text a client receives."""
    return json.dumps(RenderResult.to_json(result), default=str)


class TestTheControl:
    """The admin group may read the hidden type, so every reference resolves."""

    def test_the_plain_reference_carries_the_hidden_summary(
            self, full_access_user, database_manager, database_name) -> None:
        """The reference block names the hidden object and its summary value"""
        reference = _field(_result(full_access_user, database_manager, database_name), seed.REF_FIELD)[
            RenderedFieldKey.REFERENCE]

        assert reference['object_id'] == seed.HIDDEN_ID
        assert [summary['value'] for summary in reference['summaries']] == [seed.HIDDEN_VALUE]

    def test_the_reference_section_pulls_the_hidden_values(
            self, full_access_user, database_manager, database_name) -> None:
        """A section on the hidden object answers its values"""
        result = _result(full_access_user, database_manager, database_name)

        assert _section_values(result, seed.HIDDEN_SECTION) == [seed.HIDDEN_VALUE]


class TestAReferenceTheUserMayNotRead:
    """The default user group may not read the hidden type."""

    def test_the_plain_reference_is_the_empty_one(self, database_manager, database_name) -> None:
        """No label, no icon, no summary - the empty reference an unset field answers"""
        field = _field(_result(seed.default_user(), database_manager, database_name), seed.REF_FIELD)

        assert field[RenderedFieldKey.REFERENCE] == TypeReference.to_json(TypeReference.empty())

    def test_the_plain_reference_keeps_its_stored_id(self, database_manager, database_name) -> None:
        """A client saves the whole object back, so the id it cannot see must survive the round trip"""
        field = _field(_result(seed.default_user(), database_manager, database_name), seed.REF_FIELD)

        assert field[FieldKey.VALUE] == seed.HIDDEN_ID

    def test_the_reference_section_answers_no_values(self, database_manager, database_name) -> None:
        """The section keeps its shape - the hidden type's fields - and answers none of the values"""
        result = _result(seed.default_user(), database_manager, database_name)

        assert _section_values(result, seed.HIDDEN_SECTION) == [None]
        assert _field(result, seed.section_field(seed.HIDDEN_SECTION))[FieldKey.VALUE] == seed.HIDDEN_ID

    def test_the_hidden_value_is_nowhere_in_the_render(self, database_manager, database_name) -> None:
        """Not in a summary, a section or a nested section"""
        assert seed.HIDDEN_VALUE not in _as_text(_result(seed.default_user(), database_manager, database_name))

    def test_the_render_reports_no_problem(self, database_manager, database_name) -> None:
        """A marker would tell the caller that something is there"""
        assert _result(seed.default_user(), database_manager, database_name).render_problems == []

    def test_what_the_user_may_read_still_resolves(self, database_manager, database_name) -> None:
        """The section on the readable MID object answers MID's values"""
        result = _result(seed.default_user(), database_manager, database_name)

        assert seed.MID_VALUE in _section_values(result, seed.MID_SECTION)


class TestANestedReferenceSection:
    """MAIN's section on MID pulls in MID's own reference section 'hs', which points at the hidden object."""

    @staticmethod
    def _nested_values(result: RenderResult) -> list[Any]:
        """The values of the block MID's pulled-in 'hs-field' carries inside MAIN's section on MID."""
        mid_block: dict[str, Any] = _field(result, seed.section_field(seed.MID_SECTION))[RenderedFieldKey.REFERENCES]
        hs_field: dict[str, Any] = next(
            field for field in mid_block[RenderedReferenceSectionKey.FIELDS]
            if field[FieldKey.NAME] == seed.section_field(seed.NESTED_SECTION)
        )

        return [field[FieldKey.VALUE] for field in hs_field[RenderedFieldKey.REFERENCES]
                [RenderedReferenceSectionKey.FIELDS]]

    def test_the_admin_gets_the_nested_values(self, full_access_user, database_manager, database_name) -> None:
        """The control: the chain answers the hidden object's values, resolved with MID's 'hs' section"""
        assert self._nested_values(_result(full_access_user, database_manager, database_name)) \
            == [seed.HIDDEN_VALUE]

    def test_the_default_user_gets_no_values_and_no_problem(self, database_manager, database_name) -> None:
        """The hidden object was never loaded, so the nested block renders like an unset one"""
        result = _result(seed.default_user(), database_manager, database_name)

        assert self._nested_values(result) == [None]
        assert result.render_problems == []


class TestWhatTheScopeCosts:
    """One read of the denied types per render, one read of an unreadable id."""

    def test_the_denied_types_are_read_once(self, database_manager, database_name, monkeypatch) -> None:
        """Two objects, nested renders and all - one query for the denied types"""
        reads: list[Any] = []
        original = scope_module.resolve_denied_type_ids

        def _spy(user: CmdbUser, permission: Any) -> list[int]:
            reads.append(user)
            return original(user, permission)

        monkeypatch.setattr(scope_module, 'resolve_denied_type_ids', _spy)

        _render_main(seed.default_user(), database_manager, database_name, seed.MAIN_ID, seed.SECOND_MAIN_ID)\
            .result()

        assert len(reads) == 1

    def test_the_chain_reads_no_single_object(self, database_manager, database_name, monkeypatch) -> None:
        """Everything the chain needs was prefetched - the hidden object is never asked for one at a time"""
        reads: list[Any] = []
        original = ObjectsManager.get_object

        def _spy(manager: ObjectsManager, public_id: Any, *args: Any, **kwargs: Any) -> Any:
            reads.append(public_id)
            return original(manager, public_id, *args, **kwargs)

        monkeypatch.setattr(ObjectsManager, 'get_object', _spy)

        _render_main(seed.default_user(), database_manager, database_name, seed.MAIN_ID, seed.SECOND_MAIN_ID)\
            .result()

        assert not reads

    def test_the_prefetch_does_not_ask_twice(self, database_manager, database_name, monkeypatch) -> None:
        """What a load did not answer is not asked for by the loads of the nested renders"""
        requested: list[set[int]] = []
        original = ObjectsManager.get_objects_lookup

        def _spy(manager: ObjectsManager, public_ids: list[int], *args: Any) -> Any:
            requested.append(set(public_ids))
            return original(manager, public_ids, *args)

        monkeypatch.setattr(ObjectsManager, 'get_objects_lookup', _spy)

        _render_main(seed.default_user(), database_manager, database_name).result()

        assert sum(seed.HIDDEN_ID in ids for ids in requested) == 1


class TestAnUnsetReferenceSection:
    """A reference section with nothing referenced yet."""

    def test_the_type_default_is_not_answered_as_a_value(
            self, full_access_user, database_manager, database_name) -> None:
        """The pulled-in field answers no value, and keeps the type's proposal under `default`"""
        result = _result(full_access_user, database_manager, database_name)
        references = _field(result, seed.section_field(seed.UNSET_SECTION))[RenderedFieldKey.REFERENCES]
        name = next(field for field in references[RenderedReferenceSectionKey.FIELDS]
                    if field[FieldKey.NAME] == seed.NAME_FIELD)

        assert name[FieldKey.VALUE] is None
        assert name[RenderedFieldKey.DEFAULT] == seed.DEFAULT_VALUE


class TestTheMdsReference:
    """get_mds_reference for the object the render was built for."""

    def test_a_rendered_object_answers_its_own_reference(
            self, full_access_user, database_manager, database_name) -> None:
        """What the MDS reference routes ask: the object rendered, and its own reference"""
        hidden = seed.load(database_manager, database_name, seed.HIDDEN_ID)

        reference = CmdbMultiRender([hidden], full_access_user).get_mds_reference(seed.HIDDEN_ID)

        assert reference['object_id'] == seed.HIDDEN_ID
        assert reference['type_id'] == seed.HIDDEN_TYPE_ID
        assert [summary['value'] for summary in reference['summaries']] == [seed.HIDDEN_VALUE]
