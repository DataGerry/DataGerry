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
Unit tests for cmdb.manager.objects_manager summary-line helpers

Covers the private composition helper ``_compose_summary_line``, the batch type loader
``_load_types_lookup``, the orchestration in ``get_summary_line`` (refactored to delegate
composition) and the batch ``get_summary_lines_lookup``. Mongo touch-points are stubbed
via MagicMock on a ``MagicMock``-typed self so the method body runs without an actual
database connection
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.manager.objects_manager import ObjectsManager
# -------------------------------------------------------------------------------------------------------------------- #


OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_OBJECT_ID: int = 701
OTHER_OWNER_TYPE_ID: int = 51

PATH: str = 'cmdb.manager.objects_manager'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    FIXTURES                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_object_doc(public_id: int, type_id: int, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with the given public_id, type_id, and field list."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'fields': fields or [],
    }


def _make_type_mock(public_id: int, label: str, *, has_summaries: bool = False,
                    summary_fields: list[dict[str, Any]] | None = None) -> MagicMock:
    """Builds a MagicMock that quacks like a CmdbType for summary-line composition."""
    type_mock = MagicMock()
    type_mock.public_id = public_id
    type_mock.label = label
    type_mock.has_summaries.return_value = has_summaries

    summary_obj = MagicMock()
    summary_obj.fields = summary_fields or []
    type_mock.get_summary.return_value = summary_obj

    return type_mock


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _compose_summary_line                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_summary_line_returns_default_prefix_when_type_has_no_summaries() -> None:
    """A type without summaries yields 'label #id' as the entire line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


def test_compose_summary_line_omits_type_label_when_with_type_is_false() -> None:
    """with_type=False yields '#id' without the type label prefix"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock, with_type=False)

    assert result == f"#{OWNER_OBJECT_ID}"


def test_compose_summary_line_appends_summary_fields_with_separators() -> None:
    """Type with summary fields appends '- first | second' to the default prefix"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': 'web01'},
        {'name': 'fqdn', 'value': 'web01.example.com'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'hostname'}, {'name': 'fqdn'}],
    )

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - web01 | web01.example.com"


def test_compose_summary_line_falls_back_to_default_when_field_walk_raises() -> None:
    """An exception while walking summary fields produces the default prefix and does not raise"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)  # 'fields' is []
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True)
    type_mock.get_summary.side_effect = RuntimeError('boom')

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


def test_compose_summary_line_emits_none_for_missing_field_value() -> None:
    """A summary field absent from the object's fields list shows up as None in the line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': 'web01'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'hostname'}, {'name': 'missing'}],
    )

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - web01 | None"


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _load_types_lookup                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_types_lookup_returns_empty_dict_for_empty_type_ids() -> None:
    """No type ids → empty result and no DB call issued"""
    mock_self = MagicMock()

    result = ObjectsManager._load_types_lookup(mock_self, [])

    assert result == {}
    mock_self.get_many_from_other_collection.assert_not_called()


def test_load_types_lookup_returns_loaded_types_keyed_by_public_id() -> None:
    """Every successfully deserialised type lands in the result keyed by its public_id"""
    type_a = _make_type_mock(OWNER_TYPE_ID, 'Server')
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')
    mock_self = MagicMock()
    mock_self.get_many_from_other_collection.return_value = [
        {'public_id': OWNER_TYPE_ID, 'label': 'Server'},
        {'public_id': OTHER_OWNER_TYPE_ID, 'label': 'Printer'},
    ]

    with patch(f'{PATH}.CmdbType.from_data', side_effect=[type_a, type_b]):
        result = ObjectsManager._load_types_lookup(mock_self, [OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID])

    assert result == {OWNER_TYPE_ID: type_a, OTHER_OWNER_TYPE_ID: type_b}


def test_load_types_lookup_skips_types_that_fail_to_deserialise() -> None:
    """A drifted type doc that raises during deserialisation is skipped silently"""
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')
    mock_self = MagicMock()
    mock_self.get_many_from_other_collection.return_value = [
        {'public_id': OWNER_TYPE_ID, 'label': 'Broken'},
        {'public_id': OTHER_OWNER_TYPE_ID, 'label': 'Printer'},
    ]

    with patch(f'{PATH}.CmdbType.from_data', side_effect=[RuntimeError('drifted'), type_b]):
        result = ObjectsManager._load_types_lookup(mock_self, [OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID])

    assert result == {OTHER_OWNER_TYPE_ID: type_b}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_summary_line                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_summary_line_returns_empty_string_for_falsy_public_id() -> None:
    """public_id of 0 or None short-circuits to an empty line before any DB call"""
    mock_self = MagicMock()

    assert ObjectsManager.get_summary_line(mock_self, 0) == ''
    mock_self.get_object.assert_not_called()


def test_get_summary_line_returns_empty_string_when_object_not_found() -> None:
    """A missing CmdbObject yields '' without attempting to compose"""
    mock_self = MagicMock()
    mock_self.get_object.return_value = None

    assert ObjectsManager.get_summary_line(mock_self, OWNER_OBJECT_ID) == ''


def test_get_summary_line_returns_empty_string_when_object_type_not_found() -> None:
    """A CmdbObject without a resolvable type yields '' (no _compose_summary_line call)"""
    mock_self = MagicMock()
    mock_self.get_object.return_value = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    mock_self.get_object_type.return_value = None

    result = ObjectsManager.get_summary_line(mock_self, OWNER_OBJECT_ID)

    assert result == ''
    mock_self._compose_summary_line.assert_not_called()


def test_get_summary_line_delegates_to_compose_summary_line_on_happy_path() -> None:
    """When the object + type both resolve, composition is delegated to _compose_summary_line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')
    mock_self = MagicMock()
    mock_self.get_object.return_value = obj_doc
    mock_self.get_object_type.return_value = type_mock
    mock_self._compose_summary_line.return_value = f"Server #{OWNER_OBJECT_ID}"

    result = ObjectsManager.get_summary_line(mock_self, OWNER_OBJECT_ID, with_type=True)

    assert result == f"Server #{OWNER_OBJECT_ID}"
    mock_self._compose_summary_line.assert_called_once_with(obj_doc, type_mock, with_type=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_summary_lines_lookup                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_summary_lines_lookup_returns_empty_dict_for_empty_input() -> None:
    """No public_ids → empty result and no DB call issued"""
    mock_self = MagicMock()

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [])

    assert result == {}
    mock_self.find_objects.assert_not_called()


def test_get_summary_lines_lookup_dedups_public_ids_before_bulk_fetch() -> None:
    """Duplicate ids in the input are collapsed in the find_objects criteria"""
    mock_self = MagicMock()
    mock_self.find_objects.return_value = []
    mock_self._load_types_lookup.return_value = {}

    ObjectsManager.get_summary_lines_lookup(
        mock_self,
        [OWNER_OBJECT_ID, OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID],
    )

    call_kwargs = mock_self.find_objects.call_args.kwargs
    in_clause = call_kwargs['criteria']['public_id']['$in']
    assert sorted(in_clause) == sorted({OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID})


def test_get_summary_lines_lookup_maps_each_object_to_its_summary_line() -> None:
    """Happy path: each resolved object/type pair produces one summary line in the result"""
    obj_a = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    obj_b = _make_object_doc(OTHER_OWNER_OBJECT_ID, OTHER_OWNER_TYPE_ID)
    type_a = _make_type_mock(OWNER_TYPE_ID, 'Server')
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')

    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj_a, obj_b]
    mock_self._load_types_lookup.return_value = {OWNER_TYPE_ID: type_a, OTHER_OWNER_TYPE_ID: type_b}
    mock_self._compose_summary_line.side_effect = lambda obj, t, with_type=True: f"{t.label} #{obj['public_id']}"

    result = ObjectsManager.get_summary_lines_lookup(
        mock_self, [OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID],
    )

    assert result == {
        OWNER_OBJECT_ID: f"Server #{OWNER_OBJECT_ID}",
        OTHER_OWNER_OBJECT_ID: f"Printer #{OTHER_OWNER_OBJECT_ID}",
    }


def test_get_summary_lines_lookup_skips_object_when_type_unresolvable() -> None:
    """An object whose type does not load is silently absent from the result"""
    obj_a = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    obj_b = _make_object_doc(OTHER_OWNER_OBJECT_ID, OTHER_OWNER_TYPE_ID)
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')

    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj_a, obj_b]
    mock_self._load_types_lookup.return_value = {OTHER_OWNER_TYPE_ID: type_b}
    mock_self._compose_summary_line.side_effect = lambda obj, t, with_type=True: f"{t.label} #{obj['public_id']}"

    result = ObjectsManager.get_summary_lines_lookup(
        mock_self, [OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID],
    )

    assert OWNER_OBJECT_ID not in result
    assert OTHER_OWNER_OBJECT_ID in result


def test_get_summary_lines_lookup_skips_object_with_non_int_public_id() -> None:
    """Drifted documents whose public_id is not an int are excluded from the result"""
    obj = {'public_id': 'not-an-int', 'type_id': OWNER_TYPE_ID, 'fields': []}
    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj]
    mock_self._load_types_lookup.return_value = {OWNER_TYPE_ID: _make_type_mock(OWNER_TYPE_ID, 'Server')}

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [OWNER_OBJECT_ID])

    assert result == {}


def test_get_summary_lines_lookup_skips_object_with_non_int_type_id() -> None:
    """Objects whose type_id is non-integer never look up a CmdbType and are excluded"""
    obj = {'public_id': OWNER_OBJECT_ID, 'type_id': None, 'fields': []}
    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj]
    mock_self._load_types_lookup.return_value = {}

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [OWNER_OBJECT_ID])

    assert result == {}
