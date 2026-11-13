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
Unit tests for the person selector narrowing guard of the CmdbType update

The managers are stubs; the aggregation itself runs against MongoDB in its integration test. Pinned:

  - which selectors an update narrows: to one object, by the kinds it no longer selects, or both - widening, an
    unchanged selector, a removed or retyped field are no narrowing
  - the usage read: one aggregation on the Type's objects, the markers of the selected objects' types read in one
    projected find (none when nothing is selected), the objects holding several as the aggregation answers them
  - the blocker reads nothing without a narrowing, refuses one object while Objects hold several (naming them) and a
    dropped kind Objects hold, and passes a narrowing nothing contradicts; the guard turns it into a 400
  - the pre-check payload, and its 404 for a name that is no person selector of the Type
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_person_selector_helper as module
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    PERSON_SELECTOR_KIND_MESSAGE,
    PERSON_SELECTOR_NOT_DECLARED_MESSAGE,
    PERSON_SELECTOR_OBJECT_ID_LIMIT,
    PERSON_SELECTOR_SINGLE_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_person_selector_helper import (
    PersonFieldUsage,
    SelectorNarrowing,
    build_person_field_usage_payload,
    build_person_field_usage_pipeline,
    guard_person_selector_narrowing,
    person_selector_narrowing_blocker,
    person_selector_narrowings,
    read_person_field_usage,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 71
NAME: str = 'owner'
SEVERAL_IDS: list[int] = [501, 502]
PERSON_TYPE_ID: int = 81
GROUP_TYPE_ID: int = 82


def _selector(name: str = NAME, selectable: list[str] | None = None, multiple: bool = False) -> dict[str, Any]:
    """A person selector definition"""
    return {'type': 'person', 'name': name, 'label': name.title(),
            'selectable': selectable or ['PERSON', 'PERSON_GROUP'], 'multiple': multiple}


def _type(*fields: dict[str, Any]) -> Any:
    """A stored type stand-in"""
    return SimpleNamespace(public_id=TYPE_ID, get_fields=lambda: list(fields))


def _managers(aggregated: list[dict[str, Any]], types: list[dict[str, Any]] | None = None) -> dict[Any, MagicMock]:
    """The objects manager answering the aggregation, the types manager answering the marker read"""
    objects, types_manager = MagicMock(), MagicMock()
    objects.aggregate_all.return_value = aggregated
    types_manager.find.return_value = types or []

    return {ManagerType.OBJECTS: objects, ManagerType.TYPES: types_manager}


def _provided(managers: dict[Any, MagicMock]) -> Any:
    """Patches the ManagerProvider to hand out the given managers"""
    return patch.object(module.ManagerProvider, 'get_manager', side_effect=lambda kind, _user: managers[kind])


class TestNarrowings:
    """person_selector_narrowings"""

    @pytest.mark.parametrize('old, new, expected', [
        (_selector(multiple=True), _selector(), [SelectorNarrowing(NAME, True, [])]),
        (_selector(), _selector(selectable=['PERSON']), [SelectorNarrowing(NAME, False, ['PERSON_GROUP'])]),
        (_selector(multiple=True), _selector(selectable=['PERSON_GROUP']), [SelectorNarrowing(NAME, True, ['PERSON'])]),
        (_selector(), _selector(multiple=True), []),
        (_selector(selectable=['PERSON']), _selector(), []),
        (_selector(), _selector(), []),
    ], ids=['to-one', 'kind-dropped', 'both', 'to-several', 'kind-added', 'unchanged'])
    def test_what_an_update_narrows(self, old: dict[str, Any], new: dict[str, Any],
                                    expected: list[SelectorNarrowing]) -> None:
        """Widening is never a narrowing"""
        assert person_selector_narrowings([old], [new]) == expected

    def test_a_removed_or_retyped_field_is_no_narrowing(self) -> None:
        """Its values go by the type alignment, as for every other kind"""
        assert person_selector_narrowings([_selector(multiple=True)], []) == []
        assert person_selector_narrowings([_selector(multiple=True)], [{'type': 'text', 'name': NAME}]) == []
        assert person_selector_narrowings([{'type': 'text', 'name': NAME}], [_selector()]) == []


def test_the_usage_pipeline_shape() -> None:
    """Match the type, project the selected values, one facet for the objects holding several and one for the types"""
    pipeline = build_person_field_usage_pipeline(TYPE_ID, NAME)

    assert [next(iter(stage)) for stage in pipeline] == ['$match', '$project', '$facet']
    assert pipeline[0] == {'$match': {'type_id': TYPE_ID}}
    several = pipeline[2]['$facet']['several']
    assert [next(iter(stage)) for stage in several] == ['$match', '$sort', '$limit', '$project']
    assert several[2] == {'$limit': PERSON_SELECTOR_OBJECT_ID_LIMIT}
    types = pipeline[2]['$facet']['selected_types']
    assert [next(iter(stage)) for stage in types] == ['$project', '$unwind', '$group', '$lookup', '$unwind', '$group']
    assert types[3]['$lookup']['from'] == CmdbObject.COLLECTION


class TestReadUsage:
    """read_person_field_usage"""

    def test_the_markers_of_the_selected_types(self) -> None:
        """One projected read of the types; a type without a marker counts for nothing"""
        managers = _managers(
            [{'several': [{'public_id': 501}], 'selected_types': [{'_id': PERSON_TYPE_ID}, {'_id': 99}]}],
            [{'special_type': 'PERSON'}, {'special_type': ''}],
        )

        with _provided(managers):
            usage = read_person_field_usage(MagicMock(), TYPE_ID, NAME)

        assert usage == PersonFieldUsage(objects_with_several=[501], kinds_used=['PERSON'])
        assert managers[ManagerType.TYPES].find.call_args.args[0] == {'public_id': {'$in': [PERSON_TYPE_ID, 99]}}

    def test_nothing_selected_reads_no_type(self) -> None:
        """Also when the type has no object at all"""
        managers = _managers([])

        with _provided(managers):
            assert read_person_field_usage(MagicMock(), TYPE_ID, NAME) == PersonFieldUsage([], [])

        managers[ManagerType.TYPES].find.assert_not_called()


class TestBlocker:
    """person_selector_narrowing_blocker and its guard"""

    def test_no_narrowing_reads_nothing(self) -> None:
        """A widening or an unrelated edit"""
        managers = _managers([])

        with _provided(managers):
            assert person_selector_narrowing_blocker(MagicMock(), _type(_selector()), _type(_selector(multiple=True))) \
                is None

        managers[ManagerType.OBJECTS].aggregate_all.assert_not_called()

    def test_one_object_while_objects_hold_several_is_refused(self) -> None:
        """Naming them"""
        with _provided(_managers([{'several': [{'public_id': i} for i in SEVERAL_IDS], 'selected_types': []}])):
            assert person_selector_narrowing_blocker(
                MagicMock(), _type(_selector(multiple=True)), _type(_selector()),
            ) == PERSON_SELECTOR_SINGLE_MESSAGE.format(name=NAME, object_ids=SEVERAL_IDS)

    def test_a_dropped_kind_objects_hold_is_refused(self) -> None:
        """Only the dropped kinds that are held"""
        managers = _managers([{'several': [], 'selected_types': [{'_id': GROUP_TYPE_ID}]}],
                             [{'special_type': 'PERSON_GROUP'}])

        with _provided(managers):
            assert person_selector_narrowing_blocker(
                MagicMock(), _type(_selector()), _type(_selector(selectable=['PERSON'])),
            ) == PERSON_SELECTOR_KIND_MESSAGE.format(name=NAME, kinds=['PERSON_GROUP'])

    def test_a_narrowing_nothing_contradicts_passes(self) -> None:
        """No object holds several, none a dropped kind"""
        managers = _managers([{'several': [], 'selected_types': [{'_id': PERSON_TYPE_ID}]}],
                             [{'special_type': 'PERSON'}])

        with _provided(managers):
            assert person_selector_narrowing_blocker(
                MagicMock(), _type(_selector(multiple=True)), _type(_selector(selectable=['PERSON'])),
            ) is None

    def test_the_guard_answers_the_refusal_as_a_400(self) -> None:
        """The update route's wrapper"""
        with patch.object(module, 'person_selector_narrowing_blocker', return_value='refused'), \
                pytest.raises(HTTPException) as caught:
            guard_person_selector_narrowing(MagicMock(), _type(), _type())

        assert (caught.value.code, caught.value.description) == (400, 'refused')


class TestPayload:
    """build_person_field_usage_payload"""

    def test_the_usage_of_a_declared_selector(self) -> None:
        """Under the documented keys"""
        managers = _managers([{'several': [{'public_id': 501}], 'selected_types': [{'_id': PERSON_TYPE_ID}]}],
                             [{'special_type': 'PERSON'}])

        with _provided(managers):
            assert build_person_field_usage_payload(MagicMock(), _type(_selector()), NAME) == {
                'objects_with_several': [501], 'kinds_used': ['PERSON'],
            }

    @pytest.mark.parametrize('fields', [[], [{'type': 'text', 'name': NAME}]], ids=['undeclared', 'another-kind'])
    def test_a_name_that_is_no_selector_is_a_404(self, fields: list[dict[str, Any]]) -> None:
        """Nothing is read"""
        managers = _managers([])

        with _provided(managers), pytest.raises(HTTPException) as caught:
            build_person_field_usage_payload(MagicMock(), _type(*fields), NAME)

        assert (caught.value.code, caught.value.description) == (
            404, PERSON_SELECTOR_NOT_DECLARED_MESSAGE.format(public_id=TYPE_ID, name=NAME))
        managers[ManagerType.OBJECTS].aggregate_all.assert_not_called()
