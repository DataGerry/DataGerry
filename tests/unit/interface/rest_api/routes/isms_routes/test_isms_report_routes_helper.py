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
Unit tests for the pure helpers of isms_report_routes

Two of them, both pure and both isolated from Mongo:

``sort_key`` orders control measures ISO-27001:2022-source-first, then by a natural (numeric-aware)
identifier order, with empty identifiers last - and must never raise when identifiers of different
shapes are compared.

``resolve_assessed_objects`` names a report row's assessed object: an object's public_id becomes its
summary line, the whole page resolved in **one** batched lookup rather than one per row; an object or a
group that no longer resolves is labelled rather than left blank or bare; and the internal
``object_id_ref_type`` is dropped from every row. The summaries are read as the reader, READ-scoped; an
object of a type the reader may not READ is blanked - not named, and not called 'Unknown object' either.
It is driven here with a stub manager, since what matters is how many times it asks and what it does with
the answer.
"""
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import (
    HIDDEN_OBJECT_LABEL,
    UNKNOWN_OBJECT_GROUP_LABEL,
    UNKNOWN_OBJECT_LABEL,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import hidden_object_ids, resolve_assessed_objects
from cmdb.interface.rest_api.routes.isms_routes.isms_report_routes import SOA_PROJECTION, sort_key
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

ISO_SOURCE: str = 'ISO 27001:2022'


def _cm(source: str = 'Other', identifier: str = '') -> dict[str, Any]:
    """Builds a control-measure dict with the fields sort_key reads."""
    return {'source': source, 'identifier': identifier}


def _sorted_identifiers(control_measures: list[dict[str, Any]]) -> list[str]:
    """Returns the identifiers of the control measures in sort_key order."""
    return [cm['identifier'] for cm in sorted(control_measures, key=sort_key)]


def test_iso_source_sorts_first() -> None:
    """A control measure with the ISO 27001:2022 source is ordered before others."""
    control_measures = [_cm(source='Other', identifier='1'), _cm(source=ISO_SOURCE, identifier='9')]

    assert sorted(control_measures, key=sort_key)[0]['source'] == ISO_SOURCE


def test_empty_identifier_sorts_last() -> None:
    """Within the same source, an empty identifier is ordered after a non-empty one."""
    assert _sorted_identifiers([_cm(identifier=''), _cm(identifier='1')]) == ['1', '']


def test_identifiers_sort_numerically() -> None:
    """Identifier segments are compared numerically, so 5.2 precedes 5.10."""
    assert _sorted_identifiers([_cm(identifier='5.10'), _cm(identifier='5.2')]) == ['5.2', '5.10']


def test_heterogeneous_identifiers_do_not_raise() -> None:
    """Mixing numeric and alphabetic identifiers must not raise a TypeError."""
    control_measures = [_cm(identifier='A'), _cm(identifier='12'), _cm(identifier='A.1'), _cm(identifier='3')]

    ordered = _sorted_identifiers(control_measures)

    # Numeric identifiers sort before alphabetic ones (digit groups rank before non-digit groups)
    assert ordered == ['3', '12', 'A', 'A.1']

# ------------------------------------------------- SOA_PROJECTION ------------------------------------------------- #

def test_soa_projection_keeps_the_keys_sort_key_orders_by() -> None:
    """Projecting away the source or identifier would leave sort_key ordering every row as empty"""
    assert SOA_PROJECTION[ControlMeasureKey.SOURCE.value] == 1
    assert SOA_PROJECTION[ControlMeasureKey.IDENTIFIER.value] == 1


def test_soa_projection_is_the_report_columns_without_description_or_id() -> None:
    """The SOA reads exactly its columns: the free-text description is not loaded and `_id` is excluded"""
    included = {key for key, flag in SOA_PROJECTION.items() if flag == 1}

    assert included == {
        ControlMeasureKey.PUBLIC_ID.value, ControlMeasureKey.IDENTIFIER.value, ControlMeasureKey.TITLE.value,
        ControlMeasureKey.CHAPTER.value, ControlMeasureKey.IS_APPLICABLE.value, ControlMeasureKey.REASON.value,
        ControlMeasureKey.IMPLEMENTATION_STATE.value, ControlMeasureKey.CONTROL_MEASURE_TYPE.value,
        ControlMeasureKey.SOURCE.value,
    }
    assert SOA_PROJECTION['_id'] == 0
    assert ControlMeasureKey.DESCRIPTION.value not in SOA_PROJECTION

# ------------------------------------------- resolve_assessed_objects --------------------------------------------- #

OBJECT_KEY: str = 'object'


# The reader the stub sees - any object; the stub only checks it is passed through
READER: object = object()
# A type the reader may not READ, and one they may
DENIED_TYPE: int = 7
READABLE_TYPE: int = 8


class _StubObjectsManager:
    """
    Stub ObjectsManager serving a fixed summary lookup and recording each call it receives

    ``summaries`` are the lines the reader's scoped read answers; ``stored`` maps the ids that exist without a
    readable line to their type_id, served by the unscoped existence read
    """

    def __init__(self, summaries: dict[int, str], stored: dict[int, int] | None = None) -> None:
        self._summaries: dict[int, str] = summaries
        self._stored: dict[int, int] = stored or {}
        self.calls: list[list[int]] = []
        self.scopes: list[tuple[Any, Any]] = []
        self.existence_reads: list[dict[str, Any]] = []

    # with_type is part of the real signature and is asserted on by its own test below
    # pylint: disable=unused-argument
    def get_summary_lines_lookup(
            self,
            object_ids: list[int],
            with_type: bool = True,
            user: Any = None,
            permission: Any = None,
        ) -> dict[int, str]:
        """Records the ids and the scope it was asked for and answers from the fixed lookup"""
        self.calls.append(list(object_ids))
        self.scopes.append((user, permission))

        return {object_id: self._summaries[object_id]
                for object_id in object_ids if object_id in self._summaries}

    def find_objects(
            self,
            criteria: dict[str, Any],
            as_dict: bool = False,
            projection: dict[str, Any] | None = None,
        ) -> list[dict[str, Any]]:
        """Records the existence read and answers the stored ids matching both of its $in clauses"""
        self.existence_reads.append(criteria)
        ids: list[int] = criteria['public_id']['$in']
        type_ids: list[int] = criteria['type_id']['$in']

        return [{'public_id': object_id} for object_id, type_id in self._stored.items()
                if object_id in ids and type_id in type_ids]


def _resolve(rows: list[dict[str, Any]], manager: Any, denied: list[int] | None = None) -> None:
    """Runs resolve_assessed_objects for READER with the given denied types (none by default)"""
    resolve_assessed_objects(rows, OBJECT_KEY, manager, READER, denied or [])


REF_KEY: str = 'object_id_ref_type'
# A row with no value under the object key, as the projection leaves a deleted group's name
ABSENT: object = object()


def _row(object_id: Any, ref_type: Any = ObjectReferenceType.OBJECT) -> dict[str, Any]:
    """
    Builds a report row as the aggregation projects it

    Args:
        object_id (Any): The value under the object key, or ABSENT to leave the key out
        ref_type (Any): The row's object_id_ref_type, or ABSENT to leave the key out

    Returns:
        dict[str, Any]: A single report row
    """
    row: dict[str, Any] = {}

    if object_id is not ABSENT:
        row[OBJECT_KEY] = object_id

    if ref_type is not ABSENT:
        row[REF_KEY] = ref_type

    return row


def test_every_object_row_is_resolved_in_one_batch() -> None:
    """
    The whole page is resolved with a single lookup

    This is the helper's reason to exist: the rows are already in memory, so resolving them one at a
    time would be an N+1 against framework.objects for every report page.
    """
    rows = [_row(10), _row(11), _row(12)]
    manager = _StubObjectsManager({10: 'Server A', 11: 'Server B', 12: 'Server C'})

    _resolve(rows, manager)

    assert manager.calls == [[10, 11, 12]]
    assert [row[OBJECT_KEY] for row in rows] == ['Server A', 'Server B', 'Server C']


def test_an_unresolvable_id_is_labelled_rather_than_left_bare() -> None:
    """A row naming a deleted object is exactly what a reader needs to see, so it is kept and named."""
    rows = [_row(10), _row(99)]
    manager = _StubObjectsManager({10: 'Server A'})

    _resolve(rows, manager)

    assert rows[0][OBJECT_KEY] == 'Server A'
    assert rows[1][OBJECT_KEY] == UNKNOWN_OBJECT_LABEL


def test_object_group_rows_are_left_alone() -> None:
    """
    Only OBJECT rows carry an object public_id

    An OBJECT_GROUP row's value is already the group's name, projected by the pipeline - resolving it
    as an object id would replace a name with 'Unknown object'.
    """
    rows = [_row('My group', ObjectReferenceType.OBJECT_GROUP), _row(10)]
    manager = _StubObjectsManager({10: 'Server A'})

    _resolve(rows, manager)

    assert rows[0][OBJECT_KEY] == 'My group'
    assert manager.calls == [[10]]


def test_nothing_is_asked_when_no_row_needs_resolving() -> None:
    """An empty page, or a page of group rows only, must not reach the database at all."""
    rows = [_row('My group', ObjectReferenceType.OBJECT_GROUP), _row(None)]
    manager = _StubObjectsManager({10: 'Server A'})

    _resolve(rows, manager)
    _resolve([], manager)

    assert len(manager.calls) == 0


def test_the_summary_is_requested_without_the_type_prefix() -> None:
    """The report has its own object_type column, so the summary must not repeat the type."""
    manager = _StubObjectsManager({10: 'Server A'})

    class _Recorder(_StubObjectsManager):
        """Records the with_type flag as well"""

        def __init__(self, summaries: dict[int, str]) -> None:
            super().__init__(summaries)
            self.with_type_flags: list[bool] = []

        def get_summary_lines_lookup(
                self,
                object_ids: list[int],
                with_type: bool = True,
                user: Any = None,
                permission: Any = None,
            ) -> dict[int, str]:
            """Records the flag, then delegates"""
            self.with_type_flags.append(with_type)

            return super().get_summary_lines_lookup(object_ids, with_type, user, permission)

    recorder = _Recorder({10: 'Server A'})
    _resolve([_row(10)], recorder)

    assert recorder.with_type_flags == [False]
    assert len(manager.calls) == 0


def test_the_ref_type_is_dropped_from_every_row() -> None:
    """Both reports answer without the internal discriminator - object, group and empty rows alike"""
    rows = [_row(10), _row('My group', ObjectReferenceType.OBJECT_GROUP), _row(None, None)]

    _resolve(rows, _StubObjectsManager({10: 'Server A'}))

    assert all(REF_KEY not in row for row in rows)


def test_a_deleted_group_is_labelled() -> None:
    """The projection leaves a deleted group's name absent; the row is named, not left blank"""
    rows = [_row(ABSENT, ObjectReferenceType.OBJECT_GROUP), _row('My group', ObjectReferenceType.OBJECT_GROUP)]

    _resolve(rows, _StubObjectsManager({}))

    assert [row[OBJECT_KEY] for row in rows] == [UNKNOWN_OBJECT_GROUP_LABEL, 'My group']


def test_a_row_without_a_ref_type_is_resolved_as_an_object() -> None:
    """A legacy assessment reads as an object, as the projection reads it - not as a bare id"""
    rows = [_row(10, ABSENT), _row(99, ABSENT)]

    _resolve(rows, _StubObjectsManager({10: 'Server A'}))

    assert [row[OBJECT_KEY] for row in rows] == ['Server A', UNKNOWN_OBJECT_LABEL]


def test_a_row_with_no_assessed_object_is_left_as_it_is() -> None:
    """No id, no ref type: there is nothing to name, and nothing is asked"""
    rows = [_row(None, None), _row(ABSENT, ABSENT)]
    manager = _StubObjectsManager({})

    _resolve(rows, manager)

    assert rows == [{OBJECT_KEY: None}, {}]
    assert not manager.calls


def test_a_bool_is_not_an_object_id() -> None:
    """True == 1 in Python; it is not resolved as object 1"""
    rows = [_row(True)]
    manager = _StubObjectsManager({1: 'Server One'})

    _resolve(rows, manager)

    assert rows[0][OBJECT_KEY] is True
    assert not manager.calls


def test_the_summaries_are_read_as_the_reader_with_read() -> None:
    """The one batch is READ-scoped to the reader - an unscoped read would name objects they may not see"""
    manager = _StubObjectsManager({10: 'Server A'})

    _resolve([_row(10)], manager)

    assert manager.scopes == [(READER, AccessControlPermission.READ)]


def test_an_object_of_a_denied_type_is_blank_not_unknown() -> None:
    """
    Hidden, missing and readable rows each get their own answer

    The hidden object exists: 'Unknown object' would be a false claim that it is gone, so it is blanked.
    The missing one stays 'Unknown object', and the readable one is named
    """
    rows = [_row(10), _row(11), _row(99)]
    manager = _StubObjectsManager({10: 'Server A'}, stored={11: DENIED_TYPE})

    _resolve(rows, manager, denied=[DENIED_TYPE])

    assert [row[OBJECT_KEY] for row in rows] == ['Server A', HIDDEN_OBJECT_LABEL, UNKNOWN_OBJECT_LABEL]


def test_an_existing_object_of_a_readable_type_without_a_line_stays_unknown() -> None:
    """Only a denied type blanks: an object whose own type is gone has no line for anyone, and is unknown"""
    rows = [_row(11)]

    _resolve(rows, _StubObjectsManager({}, stored={11: READABLE_TYPE}), denied=[DENIED_TYPE])

    assert rows[0][OBJECT_KEY] == UNKNOWN_OBJECT_LABEL


def test_the_hidden_label_is_blank() -> None:
    """Blank, so a hidden row says nothing about the object - not even that it is hidden"""
    assert HIDDEN_OBJECT_LABEL == ''


# ------------------------------------------------ hidden_object_ids ----------------------------------------------- #

def test_hidden_ids_asks_only_for_the_unresolved_ids_of_denied_types() -> None:
    """One read, narrowed to the unresolved ids and to the denied types, both sorted"""
    manager = _StubObjectsManager({}, stored={11: DENIED_TYPE, 12: READABLE_TYPE})

    assert hidden_object_ids({12, 11}, manager, [9, DENIED_TYPE]) == {11}
    assert manager.existence_reads == [{'public_id': {'$in': [11, 12]}, 'type_id': {'$in': [DENIED_TYPE, 9]}}]


def test_hidden_ids_asks_nothing_when_nothing_is_unresolved_or_denied() -> None:
    """A fully named page, or a reader who may read every type, costs no extra read"""
    manager = _StubObjectsManager({}, stored={11: DENIED_TYPE})

    assert hidden_object_ids(set(), manager, [DENIED_TYPE]) == set()
    assert hidden_object_ids({11}, manager, []) == set()
    assert not manager.existence_reads
