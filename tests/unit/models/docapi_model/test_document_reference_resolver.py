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
Unit tests for cmdb.models.docapi_model.document_reference_resolver

Pure tests: `CmdbMultiRender` and the managers are mocked. Covers the field predicates, the per-level id collection
(both template modes), and the resolver method by method - adopting a render's prefetch, rendering only what is not
rendered, preparing level by level, a reference no level reached, the one READ-scoped load per level, and the
location names read once per document
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from cmdb.models.docapi_model.document_reference_resolver import (
    DocumentReferenceResolver,
    collect_reference_ids,
    followed_reference_id,
    is_location_field,
)
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_constants import DG_LOCATION_FIELD_NAME
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.locations_manager import LocationsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.document_reference_resolver'

REF: str = FieldType.REFERENCE.value
LOCATION: str = FieldType.LOCATION.value
REF_SECTION: str = FieldType.REF_SECTION.value
TEXT: str = FieldType.TEXT.value

ROOT_ID: int = 1
MID_ID: int = 21
SIDE_ID: int = 22
LEAF_ID: int = 31
HIDDEN_ID: int = 41
LOCATION_ID: int = 77


def _ref(public_id: Any, name: str = 'ref') -> dict[str, Any]:
    """A rendered REFERENCE field"""
    return {'name': name, 'type': REF, 'value': public_id}


def _object(public_id: int) -> SimpleNamespace:
    """A CmdbObject stand-in"""
    return SimpleNamespace(public_id=public_id)


def _render(public_id: int, *fields: dict[str, Any]) -> SimpleNamespace:
    """A RenderResult stand-in"""
    return SimpleNamespace(object_information={'object_id': public_id}, fields=list(fields))


def _resolver(objects_manager: Mock | None = None) -> DocumentReferenceResolver:
    """A resolver for a mocked user and objects manager"""
    return DocumentReferenceResolver(Mock(name='request_user'), objects_manager or Mock(name='objects_manager'))


def _renderer(results: list[SimpleNamespace], cache: dict[int, Any] | None = None,
              unreturned: set[int] | None = None) -> Mock:
    """A CmdbMultiRender stand-in answering the given results and prefetch"""
    return Mock(result=Mock(return_value=results), objects_cache=cache or {},
                read_scope=Mock(unreturned_ids=unreturned or set()))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   field predicates                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsLocationField:
    """A location field is never followed as an object reference."""

    @pytest.mark.parametrize('name,field_type,expected', [
        ('placement', LOCATION, True),
        (DG_LOCATION_FIELD_NAME, TEXT, True),
        ('ref', REF, False),
        ('text', TEXT, False),
    ])
    def test_by_type_or_reserved_name(self, name: str, field_type: str, expected: bool) -> None:
        """Whatever its name a LOCATION field is one; so is the reserved name, whatever its type"""
        assert is_location_field(name, field_type) is expected


class TestFollowedReferenceId:
    """The id a rendered field leads a document to."""

    def test_a_set_reference(self) -> None:
        """Its value"""
        assert followed_reference_id(_ref(MID_ID)) == MID_ID

    @pytest.mark.parametrize('value', [None, 0, '', '21', True, 2.5])
    def test_an_unset_or_non_integer_value_is_not_followed(self, value: Any) -> None:
        """Only a real public_id is followed - the resolver renders anything else on its own, or not at all"""
        assert followed_reference_id(_ref(value)) is None

    @pytest.mark.parametrize('field', [
        {'name': 'placement', 'type': LOCATION, 'value': LOCATION_ID},
        {'name': DG_LOCATION_FIELD_NAME, 'type': REF, 'value': LOCATION_ID},
        {'name': 'text', 'type': TEXT, 'value': MID_ID},
    ])
    def test_a_location_or_plain_field_is_not_followed(self, field: dict[str, Any]) -> None:
        """A location id is not an object id; a plain field leads nowhere"""
        assert followed_reference_id(field) is None


class TestCollectReferenceIds:
    """One hop's ids, mirroring ObjectTemplateData's dispatch."""

    SECTION: dict[str, Any] = {'name': 'ms', 'type': REF_SECTION, 'references': {'fields': [
        _ref(SIDE_ID, 'inner'),
        {'name': 'nested', 'type': REF_SECTION, 'references': {'fields': [_ref(LEAF_ID, 'deep')]}},
        {'name': 'placement', 'type': LOCATION, 'value': LOCATION_ID},
    ]}}

    def test_plain_references_in_both_modes(self) -> None:
        """Locations and unset references left out"""
        fields = [_ref(MID_ID), _ref(None, 'unset'), {'name': 'placement', 'type': LOCATION, 'value': LOCATION_ID}]

        assert collect_reference_ids(fields, True) == collect_reference_ids(fields, False) == {MID_ID}

    def test_a_default_template_follows_references_inside_reference_sections(self) -> None:
        """At any nesting, at the same hop"""
        assert collect_reference_ids([_ref(MID_ID), self.SECTION], True) == {MID_ID, SIDE_ID, LEAF_ID}

    def test_an_object_template_does_not(self) -> None:
        """A legacy reference section is flattened to its values, nothing in it is followed"""
        assert collect_reference_ids([_ref(MID_ID), self.SECTION], False) == {MID_ID}

    @pytest.mark.parametrize('fields', [None, []])
    def test_no_fields(self, fields: Any) -> None:
        """Nothing to follow"""
        assert collect_reference_ids(fields, True) == set()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               DocumentReferenceResolver                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAdopt:
    """What a render loaded becomes the document's."""

    def test_the_prefetch_and_its_refusals_are_taken(self) -> None:
        """Prefetched objects are known; an id it asked for and did not get is unresolvable"""
        resolver = _resolver()
        mid = _object(MID_ID)

        resolver.adopt(_renderer([], cache={MID_ID: mid}, unreturned={HIDDEN_ID}))

        assert resolver.objects == {MID_ID: mid}
        assert resolver.unresolvable == {HIDDEN_ID}

    def test_an_id_a_later_load_returned_is_not_marked(self) -> None:
        """Known objects win over an earlier refusal of the same id"""
        resolver = _resolver()
        resolver.objects[HIDDEN_ID] = _object(HIDDEN_ID)

        resolver.adopt(_renderer([], unreturned={HIDDEN_ID}))

        assert HIDDEN_ID not in resolver.unresolvable


class TestRenderObjects:
    """One render per call, for what is not rendered yet."""

    @patch(f'{MODULE}.CmdbMultiRender')
    def test_pending_objects_are_rendered_once_together(self, multi_render: Mock) -> None:
        """For the document's user, references resolved; stored by id and adopted"""
        resolver = _resolver()
        leaf = _object(LEAF_ID)
        multi_render.return_value = _renderer([_render(MID_ID), _render(SIDE_ID)], cache={LEAF_ID: leaf})
        objects = [_object(MID_ID), _object(SIDE_ID)]

        results = resolver.render_objects(objects)

        multi_render.assert_called_once_with(objects, resolver.request_user, ref_render=True)
        assert [r.object_information['object_id'] for r in results] == [MID_ID, SIDE_ID]
        assert set(resolver.renders) == {MID_ID, SIDE_ID}
        assert resolver.objects == {LEAF_ID: leaf}

    @patch(f'{MODULE}.CmdbMultiRender')
    def test_a_rendered_object_is_not_rendered_again(self, multi_render: Mock) -> None:
        """Answered from what the document holds, in the order asked"""
        resolver = _resolver()
        resolver.renders[MID_ID] = _render(MID_ID)
        multi_render.return_value = _renderer([_render(SIDE_ID)])

        results = resolver.render_objects([_object(SIDE_ID), _object(MID_ID)])

        assert multi_render.call_args.args[0][0].public_id == SIDE_ID
        assert len(multi_render.call_args.args[0]) == 1
        assert [r.object_information['object_id'] for r in results] == [SIDE_ID, MID_ID]

    @patch(f'{MODULE}.CmdbMultiRender')
    def test_nothing_pending_renders_nothing(self, multi_render: Mock) -> None:
        """No render is built for objects the document already rendered"""
        resolver = _resolver()
        resolver.renders[MID_ID] = _render(MID_ID)

        resolver.render_objects([_object(MID_ID)])

        multi_render.assert_not_called()

    @patch(f'{MODULE}.CmdbMultiRender')
    def test_an_object_without_a_render_is_unresolvable(self, multi_render: Mock) -> None:
        """Its type is missing - the render skipped it; it is not tried again"""
        resolver = _resolver()
        multi_render.return_value = _renderer([])

        assert not resolver.render_objects([_object(MID_ID)])
        assert resolver.unresolvable == {MID_ID}


class TestPrepare:
    """Level by level, one render per level."""

    def test_each_level_is_rendered_in_one_pass(self) -> None:
        """ROOT -> {MID, SIDE} -> {LEAF}: two levels, two renders, and the walk stops when nothing is pending"""
        resolver = _resolver()
        resolver.objects.update({i: _object(i) for i in (MID_ID, SIDE_ID, LEAF_ID)})
        renders = {MID_ID: _render(MID_ID, _ref(LEAF_ID)), SIDE_ID: _render(SIDE_ID, _ref(LEAF_ID)),
                   LEAF_ID: _render(LEAF_ID)}
        batches: list[list[int]] = []

        def _render_objects(objects: list[SimpleNamespace]) -> list[SimpleNamespace]:
            batches.append([obj.public_id for obj in objects])
            for obj in objects:
                resolver.renders[obj.public_id] = renders[obj.public_id]
            return [renders[obj.public_id] for obj in objects]

        resolver.render_objects = Mock(side_effect=_render_objects)

        resolver.prepare([_render(ROOT_ID, _ref(MID_ID), _ref(SIDE_ID, 'side'))], 3, False)

        assert batches == [[MID_ID, SIDE_ID], [LEAF_ID]]

    def test_the_depth_bounds_the_levels(self) -> None:
        """One hop asked - the second level is not rendered"""
        resolver = _resolver()
        resolver.objects.update({MID_ID: _object(MID_ID), LEAF_ID: _object(LEAF_ID)})
        resolver.render_objects = Mock(return_value=[_render(MID_ID, _ref(LEAF_ID))])

        resolver.prepare([_render(ROOT_ID, _ref(MID_ID))], 1, False)

        resolver.render_objects.assert_called_once()

    def test_rendered_and_unresolvable_ids_are_not_asked_for(self) -> None:
        """Nothing pending - no render, no load"""
        objects_manager = Mock()
        resolver = _resolver(objects_manager)
        resolver.renders[MID_ID] = _render(MID_ID)
        resolver.unresolvable.add(HIDDEN_ID)
        resolver.render_objects = Mock()

        resolver.prepare([_render(ROOT_ID, _ref(MID_ID), _ref(HIDDEN_ID, 'hidden'))], 3, False)

        resolver.render_objects.assert_not_called()
        objects_manager.get_objects_by.assert_not_called()

    def test_ids_the_prefetch_did_not_load_are_loaded_in_one_query(self) -> None:
        """A reference inside a reference section's object: loaded with the level, through READ"""
        objects_manager = Mock()
        objects_manager.get_objects_by.return_value = [_object(SIDE_ID)]
        resolver = _resolver(objects_manager)
        resolver.objects[MID_ID] = _object(MID_ID)
        resolver.render_objects = Mock(return_value=[])

        resolver.prepare([_render(ROOT_ID, _ref(MID_ID), _ref(SIDE_ID, 'side'))], 3, False)

        objects_manager.get_objects_by.assert_called_once_with(
            user=resolver.request_user, permission=AccessControlPermission.READ,
            criteria={'public_id': {'$in': [SIDE_ID]}},
        )
        assert [obj.public_id for obj in resolver.render_objects.call_args.args[0]] == [MID_ID, SIDE_ID]


class TestRenderFor:
    """The render of one referenced object."""

    def test_a_prepared_render_is_answered(self) -> None:
        """Nothing read, nothing rendered"""
        resolver = _resolver()
        resolver.renders[MID_ID] = render = _render(MID_ID)
        resolver.render_objects = Mock()

        assert resolver.render_for(MID_ID) is render
        resolver.render_objects.assert_not_called()

    def test_an_unresolvable_id_is_none_without_a_read(self) -> None:
        """Unreadable or missing - not asked for again"""
        objects_manager = Mock()
        resolver = _resolver(objects_manager)
        resolver.unresolvable.add(HIDDEN_ID)

        assert resolver.render_for(HIDDEN_ID) is None
        objects_manager.get_objects_by.assert_not_called()

    @patch(f'{MODULE}.CmdbMultiRender')
    def test_an_id_no_level_reached_is_loaded_and_rendered_now(self, multi_render: Mock) -> None:
        """Correctness does not depend on the level walk having seen it"""
        objects_manager = Mock()
        objects_manager.get_objects_by.return_value = [_object(LEAF_ID)]
        resolver = _resolver(objects_manager)
        multi_render.return_value = _renderer([render := _render(LEAF_ID)])

        assert resolver.render_for(LEAF_ID) is render

    def test_an_id_the_load_does_not_return_is_none(self) -> None:
        """Unreadable through READ - None, and remembered"""
        objects_manager = Mock()
        objects_manager.get_objects_by.return_value = []
        resolver = _resolver(objects_manager)

        assert resolver.render_for(HIDDEN_ID) is None
        assert HIDDEN_ID in resolver.unresolvable


class TestLoad:
    """The one READ-scoped query behind a level."""

    def test_a_failed_load_makes_its_ids_unresolvable(self) -> None:
        """An outage costs those references, not the document"""
        objects_manager = Mock()
        objects_manager.get_objects_by.side_effect = ObjectsManagerGetError('boom')
        resolver = _resolver(objects_manager)

        resolver._load({MID_ID, SIDE_ID})

        assert resolver.unresolvable == {MID_ID, SIDE_ID}
        assert not resolver.objects


class TestLocationName:
    """A location field's name, read once per document."""

    def test_unset_is_empty_without_a_read(self) -> None:
        """No manager is even asked for"""
        resolver = _resolver()

        with patch(f'{MODULE}.ManagerProvider') as provider:
            assert resolver.location_name(0) == ""
            provider.get_manager.assert_not_called()

    def test_read_once_per_document(self) -> None:
        """Two location fields naming one location: one read"""
        resolver = _resolver()

        with patch(f'{MODULE}.ManagerProvider') as provider:
            provider.get_manager.return_value.get_location.return_value = {'name': 'Berlin'}

            assert resolver.location_name(LOCATION_ID) == resolver.location_name(LOCATION_ID) == 'Berlin'
            provider.get_manager.return_value.get_location.assert_called_once_with(LOCATION_ID)

            resolver.location_name(LOCATION_ID + 1)

            # a second location is read with the same manager
            provider.get_manager.assert_called_once()

    @pytest.mark.parametrize('answer', [None, LocationsManagerGetError('boom')])
    def test_not_found_or_failed_is_empty(self, answer: Any) -> None:
        """Blank in the document, not a crash"""
        resolver = _resolver()

        with patch(f'{MODULE}.ManagerProvider') as provider:
            location_read = provider.get_manager.return_value.get_location
            if isinstance(answer, Exception):
                location_read.side_effect = answer
            else:
                location_read.return_value = answer

            assert resolver.location_name(LOCATION_ID) == ""
