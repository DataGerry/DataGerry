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
Unit tests for cmdb.framework.rendering.reference_prefetch.ReferencePrefetch

Pure tests: mock managers answering from an in-memory store, real CmdbObjects and CmdbTypes. Pins which
ids each hop asks for - every object of a reference-section chain is only merged, so only its own
reference-section values lead on - how every hop is narrowed by the render's read scope,
and how a failed load and a legacy untyped field are handled
"""
import logging
from typing import Any
from unittest.mock import Mock

import pytest

from cmdb.framework.rendering import reference_read_scope as scope_module
from cmdb.framework.rendering.reference_prefetch import ReferencePrefetch
from cmdb.framework.rendering.reference_read_scope import ReferenceReadScope
from cmdb.framework.rendering.render_constants import DEFAULT_RENDER_LEVEL, RenderProblemCode, RenderProblemKey
from cmdb.framework.rendering.render_problem_log import RenderProblemLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

CHAIN_TYPE_ID: int = 720
HIDDEN_TYPE_ID: int = 721
CHAIN_FIELD: str = 'chain-section-field'
PLAIN_REF_FIELD: str = 'plain-ref'
DROPPED_FIELD: str = 'dropped-from-the-type'

START_ID: int = 730
SECTION_TARGET_ID: int = 731
NESTED_ID: int = 732
NESTED_PLAIN_ID: int = 733
OTHER_START_ID: int = 734
HIDDEN_ID: int = 735


def _obj(public_id: int, section_target: int | None = None, plain_target: int | None = None) -> CmdbObject:
    """An object pointing at `section_target` through a ref-section field and at `plain_target` plainly."""
    fields: list[dict[str, Any]] = []

    if section_target is not None:
        fields.append({'type': FieldType.REF_SECTION, 'name': CHAIN_FIELD, 'value': section_target})

    if plain_target is not None:
        fields.append({'type': FieldType.REFERENCE, 'name': PLAIN_REF_FIELD, 'value': plain_target})

    return CmdbObject.from_data({
        'public_id': public_id, 'type_id': CHAIN_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'fields': fields,
    })


def _chain_type() -> CmdbType:
    """The type every chain object belongs to: one plain reference field."""
    return CmdbType.from_data(make_type_doc(
        CHAIN_TYPE_ID, 'chain-type',
        fields=[{'type': FieldType.REFERENCE, 'name': PLAIN_REF_FIELD, 'label': 'Ref', 'ref_types': [CHAIN_TYPE_ID]}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [PLAIN_REF_FIELD]}],
    ))


class _Harness:
    """A ReferencePrefetch over a mock objects manager answering from `store`, recording each request."""

    def __init__(
        self,
        store: dict[int, CmdbObject],
        cache: dict[int, CmdbObject] | None = None,
        user: Any = None,
    ) -> None:
        self.requested: list[set[int]] = []
        self.objects_manager = Mock(name='objects_manager')
        self.objects_manager.get_objects_lookup.side_effect = self._lookup
        self.types_manager = Mock(name='types_manager')
        self.problems = RenderProblemLog(logging.getLogger(__name__))
        self.store = store
        # No user reads unscoped, so the scope needs no database; a test giving one patches the denials
        self.read_scope = ReferenceReadScope(user)
        self.prefetch = ReferencePrefetch(
            self.objects_manager, self.types_manager, cache or {}, self.problems, self.read_scope,
        )

    def _lookup(self, public_ids: list[int], denied_type_ids: list[int] | None = None) -> dict[int, CmdbObject]:
        self.requested.append(set(public_ids))
        return {
            public_id: self.store[public_id] for public_id in public_ids
            if public_id in self.store and self.store[public_id].get_type_id() not in (denied_type_ids or [])
        }


class TestTheWalk:
    """Which ids each hop asks for."""

    def test_each_hop_is_one_query(self) -> None:
        """Rendered object -> section target -> the target behind its own reference section"""
        harness = _Harness({
            SECTION_TARGET_ID: _obj(SECTION_TARGET_ID, NESTED_ID),
            NESTED_ID: _obj(NESTED_ID, plain_target=NESTED_PLAIN_ID),
            NESTED_PLAIN_ID: _obj(NESTED_PLAIN_ID),
        })

        loaded = harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID)])

        assert harness.requested == [{SECTION_TARGET_ID}, {NESTED_ID}]
        assert set(loaded) == {SECTION_TARGET_ID, NESTED_ID}

    def test_no_hop_loads_a_targets_plain_references(self) -> None:
        """
        Every object of a chain is only merged, so its plain references are never loaded - at any hop

        The second hop's target is merged into the first one's section exactly like the first one is merged
        into the rendered object's: loading its plain references would change what the section shows
        """
        harness = _Harness({
            SECTION_TARGET_ID: _obj(SECTION_TARGET_ID, NESTED_ID, plain_target=NESTED_PLAIN_ID),
            NESTED_ID: _obj(NESTED_ID, plain_target=NESTED_PLAIN_ID),
            NESTED_PLAIN_ID: _obj(NESTED_PLAIN_ID),
        })

        harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID)])

        assert NESTED_PLAIN_ID not in set().union(*harness.requested)

    def test_several_rendered_objects_share_each_hop(self) -> None:
        """Two chains, still one query per hop - the point of prefetching"""
        other_target, other_nested = OTHER_START_ID + 10, OTHER_START_ID + 11
        harness = _Harness({
            SECTION_TARGET_ID: _obj(SECTION_TARGET_ID, NESTED_ID),
            NESTED_ID: _obj(NESTED_ID),
            other_target: _obj(other_target, other_nested),
            other_nested: _obj(other_nested),
        })

        harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID), _obj(OTHER_START_ID, other_target)])

        assert harness.requested == [{SECTION_TARGET_ID, other_target}, {NESTED_ID, other_nested}]

    def test_a_section_targets_plain_reference_is_not_loaded(self) -> None:
        """
        The section target is only merged, and the merge does not resolve its plain references

        Loading them would expand reference fields a reference section answers unexpanded - a change of
        what the section shows, not just of how many queries it costs
        """
        harness = _Harness({
            SECTION_TARGET_ID: _obj(SECTION_TARGET_ID, plain_target=NESTED_PLAIN_ID),
            NESTED_PLAIN_ID: _obj(NESTED_PLAIN_ID),
        })

        harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID)])

        assert harness.requested == [{SECTION_TARGET_ID}]

    def test_a_plain_reference_target_is_not_followed(self) -> None:
        """A plain reference is resolved from its target's values alone"""
        harness = _Harness({NESTED_PLAIN_ID: _obj(NESTED_PLAIN_ID, NESTED_ID), NESTED_ID: _obj(NESTED_ID)})

        harness.prefetch.load([_obj(START_ID, plain_target=NESTED_PLAIN_ID)])

        assert harness.requested == [{NESTED_PLAIN_ID}]

    def test_the_walk_stops_at_the_default_depth(self) -> None:
        """A longer chain than the default render reaches is not loaded past it"""
        chain_ids: list[int] = [START_ID + hop for hop in range(1, DEFAULT_RENDER_LEVEL + 4)]
        harness = _Harness({public_id: _obj(public_id, public_id + 1) for public_id in chain_ids})

        harness.prefetch.load([_obj(START_ID, START_ID + 1)])

        assert len(harness.requested) == DEFAULT_RENDER_LEVEL

    def test_a_cycle_ends(self) -> None:
        """The section target points back at the rendered object: the walk stops once nothing new turns up"""
        start: CmdbObject = _obj(START_ID, SECTION_TARGET_ID)
        harness = _Harness({START_ID: start, SECTION_TARGET_ID: _obj(SECTION_TARGET_ID, START_ID)})

        harness.prefetch.load([start])

        assert harness.requested == [{SECTION_TARGET_ID}, {START_ID}]

    def test_an_unknown_target_ends_its_branch(self) -> None:
        """A value pointing at an object that does not exist leads nowhere"""
        harness = _Harness({})

        assert not harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID)])
        assert harness.requested == [{SECTION_TARGET_ID}]

    def test_nothing_is_asked_for_what_is_cached(self) -> None:
        """The render's cache - an outer render's, for a nested one - is not loaded again"""
        harness = _Harness({}, cache={SECTION_TARGET_ID: _obj(SECTION_TARGET_ID)})

        assert not harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID)])
        assert not harness.requested

    def test_a_cached_section_target_is_followed(self) -> None:
        """A section target already cached is not loaded, but still leads on to its nested target"""
        harness = _Harness(
            {NESTED_PLAIN_ID: _obj(NESTED_PLAIN_ID), NESTED_ID: _obj(NESTED_ID)},
            cache={SECTION_TARGET_ID: _obj(SECTION_TARGET_ID, NESTED_ID)},
        )

        harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID, plain_target=NESTED_PLAIN_ID)])

        assert harness.requested == [{NESTED_PLAIN_ID}, {NESTED_ID}]

    def test_an_object_without_references_costs_no_query(self) -> None:
        """Nothing referenced, nothing asked for"""
        harness = _Harness({})

        assert not harness.prefetch.load([_obj(START_ID)])
        assert not harness.requested


def _hidden(public_id: int, section_target: int | None = None) -> CmdbObject:
    """An object of the type the denying user may not read."""
    hidden: CmdbObject = _obj(public_id, section_target)
    hidden.type_id = HIDDEN_TYPE_ID

    return hidden


@pytest.fixture(name='denying_user')
def fixture_denying_user(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """A user whose group may not read HIDDEN_TYPE_ID."""
    monkeypatch.setattr(scope_module, 'resolve_denied_type_ids', lambda _user, _permission: [HIDDEN_TYPE_ID])

    return Mock(name='denying_user')


class TestTheReadScope:
    """Every hop is narrowed by the render's READ ACL."""

    def test_each_hop_passes_the_denied_types(self, denying_user: Mock) -> None:
        """The bulk load is asked to leave the denied types out"""
        harness = _Harness({SECTION_TARGET_ID: _obj(SECTION_TARGET_ID)}, user=denying_user)

        harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID)])

        harness.objects_manager.get_objects_lookup.assert_called_once_with([SECTION_TARGET_ID], [HIDDEN_TYPE_ID])

    def test_an_unreadable_object_is_not_loaded(self, denying_user: Mock) -> None:
        """It never reaches the render's cache, so it renders like an unset reference"""
        harness = _Harness({HIDDEN_ID: _hidden(HIDDEN_ID)}, user=denying_user)

        assert not harness.prefetch.load([_obj(START_ID, plain_target=HIDDEN_ID)])

    def test_an_unreadable_object_leads_nowhere(self, denying_user: Mock) -> None:
        """A hidden section target is not followed into the chain behind it"""
        harness = _Harness({HIDDEN_ID: _hidden(HIDDEN_ID, NESTED_ID), NESTED_ID: _obj(NESTED_ID)}, user=denying_user)

        harness.prefetch.load([_obj(START_ID, HIDDEN_ID)])

        assert harness.requested == [{HIDDEN_ID}]

    def test_what_a_load_did_not_answer_is_recorded(self, denying_user: Mock) -> None:
        """Unreadable or gone - the load cannot tell, and records both as unreturned"""
        harness = _Harness({HIDDEN_ID: _hidden(HIDDEN_ID)}, user=denying_user)

        harness.prefetch.load([_obj(START_ID, plain_target=HIDDEN_ID, section_target=NESTED_ID)])

        assert harness.read_scope.unreturned_ids == {HIDDEN_ID, NESTED_ID}

    def test_an_unreturned_id_is_not_asked_for_again(self, denying_user: Mock) -> None:
        """A second load sharing the scope - a nested render's - skips it"""
        harness = _Harness({HIDDEN_ID: _hidden(HIDDEN_ID)}, user=denying_user)
        harness.prefetch.load([_obj(START_ID, plain_target=HIDDEN_ID)])

        assert not harness.prefetch.load([_obj(OTHER_START_ID, plain_target=HIDDEN_ID)])
        assert harness.requested == [{HIDDEN_ID}]

    def test_a_readable_object_is_loaded(self, denying_user: Mock) -> None:
        """The control: the denial is by type, so a readable reference still loads"""
        harness = _Harness({NESTED_PLAIN_ID: _obj(NESTED_PLAIN_ID)}, user=denying_user)

        assert set(harness.prefetch.load([_obj(START_ID, plain_target=NESTED_PLAIN_ID)])) == {NESTED_PLAIN_ID}
        assert harness.read_scope.unreturned_ids == set()


class TestAFailedLoad:
    """The bulk load raises."""

    def test_the_objects_that_reference_something_are_flagged(self) -> None:
        """The render continues without expansions; each object that lost them says so"""
        harness = _Harness({})
        harness.objects_manager.get_objects_lookup.side_effect = RuntimeError('database gone')

        assert not harness.prefetch.load([_obj(START_ID, SECTION_TARGET_ID), _obj(OTHER_START_ID)])

        assert harness.problems.problems_for(START_ID)[0][RenderProblemKey.CODE.value] == \
            RenderProblemCode.REFERENCES_UNAVAILABLE.value
        assert harness.problems.problems_for(OTHER_START_ID) == []


class TestLegacyUntypedFields:
    """A stored field without a 'type' key is typed from the object's type."""

    def test_an_untyped_reference_is_collected(self) -> None:
        """The type says it is a reference, so its target is loaded"""
        harness = _Harness({NESTED_PLAIN_ID: _obj(NESTED_PLAIN_ID)})
        harness.types_manager.get_type_instance.return_value = _chain_type()
        untyped: CmdbObject = _obj(START_ID)
        untyped.fields.append({'name': PLAIN_REF_FIELD, 'value': NESTED_PLAIN_ID})

        harness.prefetch.load([untyped])

        assert harness.requested == [{NESTED_PLAIN_ID}]

    def test_the_type_is_read_once_for_every_untyped_field(self) -> None:
        """Several untyped fields of one type cost one type read"""
        harness = _Harness({})
        harness.types_manager.get_type_instance.return_value = _chain_type()
        untyped: CmdbObject = _obj(START_ID)
        untyped.fields.extend([
            {'name': PLAIN_REF_FIELD, 'value': NESTED_PLAIN_ID},
            {'name': PLAIN_REF_FIELD, 'value': NESTED_ID},
        ])

        harness.prefetch.load([untyped])

        harness.types_manager.get_type_instance.assert_called_once_with(CHAIN_TYPE_ID)

    def test_a_field_the_type_dropped_is_skipped_and_logged(self, caplog) -> None:
        """The object carries data its type no longer declares: logged, not flagged, never fatal"""
        harness = _Harness({})
        harness.types_manager.get_type_instance.return_value = _chain_type()
        untyped: CmdbObject = _obj(START_ID)
        untyped.fields.append({'name': DROPPED_FIELD, 'value': NESTED_PLAIN_ID})

        with caplog.at_level(logging.WARNING):
            assert not harness.prefetch.load([untyped])

        assert DROPPED_FIELD in caplog.text
        assert harness.problems.problems_for(START_ID) == []

    def test_an_unreadable_type_skips_the_field(self) -> None:
        """Without the type the field's kind is unknown, so it leads nowhere"""
        harness = _Harness({})
        harness.types_manager.get_type_instance.return_value = None
        untyped: CmdbObject = _obj(START_ID)
        untyped.fields.append({'name': PLAIN_REF_FIELD, 'value': NESTED_PLAIN_ID})

        assert not harness.prefetch.load([untyped])
        assert not harness.requested
