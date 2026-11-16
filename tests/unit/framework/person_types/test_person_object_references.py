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
Unit tests for cmdb.framework.person_types.person_object_references

What an id of a person or group resolves to (unknown / unreadable, the hidden Types asked only when an object was
found), the names read past the denied Types, and the report's ``$lookup`` stage
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.person_types.person_object_references import (
    MarkedObjects,
    label_of,
    marked_object_lookup,
    marked_object_names,
    resolve_marked_objects,
)
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE: int = 3
HIDDEN_TYPE: int = 4


def _manager(*documents: dict[str, Any]) -> MagicMock:
    """An objects manager whose find answers the documents"""
    manager: MagicMock = MagicMock()
    manager.find.return_value = list(documents)

    return manager


def _person(public_id: int, type_id: int = PERSON_TYPE, name: Any = 'Ada') -> dict[str, Any]:
    """A person object as the projected read answers it"""
    return {'public_id': public_id, 'type_id': type_id,
            'fields': [{'name': 'first_name', 'value': 'x'}, {'name': 'display_name', 'value': name}]}


class TestResolveMarkedObjects:
    """Unknown and unreadable ids"""

    def test_one_read_of_the_marker_among_the_ids(self) -> None:
        """public_id $in (sorted, once each) and the marker"""
        manager = _manager()

        resolve_marked_objects(manager, SpecialType.PERSON, [2, 1, 2], lambda: frozenset())

        assert manager.find.call_args.args[0] == {'public_id': {'$in': [1, 2]}, 'special_type': 'PERSON'}

    def test_the_missing_and_the_hidden_are_named(self) -> None:
        """Sorted, apart"""
        manager = _manager(_person(1), _person(2, HIDDEN_TYPE))

        assert resolve_marked_objects(manager, SpecialType.PERSON, [3, 2, 1], lambda: frozenset({HIDDEN_TYPE})) == \
            MarkedObjects(unknown=[3], unreadable=[2])

    def test_no_ids_read_nothing(self) -> None:
        """Neither the objects nor the hidden Types"""
        manager = _manager()
        hidden = MagicMock()

        assert resolve_marked_objects(manager, SpecialType.PERSON, [], hidden) == MarkedObjects([], [])
        manager.find.assert_not_called()
        hidden.assert_not_called()

    def test_nothing_found_asks_no_hidden_types(self) -> None:
        """The ACL is only read for an object that exists"""
        hidden = MagicMock()

        assert resolve_marked_objects(_manager(), SpecialType.PERSON, [9], hidden) == MarkedObjects([9], [])
        hidden.assert_not_called()


class TestNames:
    """The label field's value, past the denied Types"""

    def test_label_of_reads_the_markers_label_field(self) -> None:
        """display_name for a person, name for a group; None without the field"""
        assert label_of(_person(1), SpecialType.PERSON) == 'Ada'
        assert label_of({'fields': [{'name': 'name', 'value': 'Ops'}]}, SpecialType.PERSON_GROUP) == 'Ops'
        assert label_of({'fields': None}, SpecialType.PERSON) is None
        assert label_of({'fields': ['junk']}, SpecialType.PERSON) is None

    def test_a_denied_type_gets_no_name(self) -> None:
        """Left out of the answer"""
        manager = _manager(_person(1), _person(2, HIDDEN_TYPE, 'Hidden'))

        assert marked_object_names(manager, SpecialType.PERSON, {1, 2}, [HIDDEN_TYPE]) == {1: 'Ada'}

    def test_no_ids_read_nothing(self) -> None:
        """An empty page costs no read"""
        manager = _manager()

        assert not marked_object_names(manager, SpecialType.PERSON, set(), [])
        manager.find.assert_not_called()


def test_the_lookup_joins_on_public_id_and_projects_the_name_under_its_key() -> None:
    """Index-backed equality join; marker and readable Types matched; the name under the label field's key"""
    stage = marked_object_lookup('risk_owner_id', 'owner', SpecialType.PERSON_GROUP, [5, 4, 5])['$lookup']

    assert (stage['from'], stage['localField'], stage['foreignField'], stage['as']) == (
        'framework.objects', 'risk_owner_id', 'public_id', 'owner')
    assert stage['pipeline'][0] == {'$match': {'special_type': 'PERSON_GROUP', 'type_id': {'$nin': [4, 5]}}}
    projection = stage['pipeline'][1]['$project']
    assert set(projection) == {'_id', 'public_id', 'name'}
