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

``_replace_object_ids_with_summaries`` swaps a report row's assessed-object public_id for the object's
summary line. It exists to do two things neither of which was covered before 2026-09-07: resolve the
whole page in **one** batched lookup rather than one per row, and label an id whose object no longer
resolves rather than leaving a bare number in the report. It is driven here with a stub manager, since
what matters is how many times it asks and what it does with the answer.
"""
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.isms_report_routes import (
    UNKNOWN_OBJECT_LABEL,
    _replace_object_ids_with_summaries,
    sort_key,
)
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
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
    """Mixing numeric and alphabetic identifiers must not raise a TypeError (regression)."""
    control_measures = [_cm(identifier='A'), _cm(identifier='12'), _cm(identifier='A.1'), _cm(identifier='3')]

    ordered = _sorted_identifiers(control_measures)

    # Numeric identifiers sort before alphabetic ones (digit groups rank before non-digit groups)
    assert ordered == ['3', '12', 'A', 'A.1']

# --------------------------------------- _replace_object_ids_with_summaries ----------------------------------------- #

OBJECT_KEY: str = 'object'


class _StubObjectsManager:
    """Stub ObjectsManager serving a fixed summary lookup and recording each call it receives"""

    def __init__(self, summaries: dict[int, str]) -> None:
        self._summaries: dict[int, str] = summaries
        self.calls: list[list[int]] = []

    # with_type is part of the real signature and is asserted on by its own test below
    # pylint: disable=unused-argument
    def get_summary_lines_lookup(self, object_ids: list[int], with_type: bool = True) -> dict[int, str]:
        """Records the ids it was asked for and answers from the fixed lookup"""
        self.calls.append(list(object_ids))

        return {object_id: self._summaries[object_id]
                for object_id in object_ids if object_id in self._summaries}


def _row(object_id: Any, ref_type: str = ObjectReferenceType.OBJECT) -> dict[str, Any]:
    """
    Builds a report row as the aggregation projects it

    Args:
        object_id (Any): The value under the object key
        ref_type (str): The row's object_id_ref_type

    Returns:
        dict[str, Any]: A single report row
    """
    return {OBJECT_KEY: object_id, 'object_id_ref_type': ref_type}


def test_every_object_row_is_resolved_in_one_batch() -> None:
    """
    The whole page is resolved with a single lookup

    This is the helper's reason to exist: the rows are already in memory, so resolving them one at a
    time would be an N+1 against framework.objects for every report page.
    """
    rows = [_row(10), _row(11), _row(12)]
    manager = _StubObjectsManager({10: 'Server A', 11: 'Server B', 12: 'Server C'})

    _replace_object_ids_with_summaries(rows, OBJECT_KEY, manager)

    assert manager.calls == [[10, 11, 12]]
    assert [row[OBJECT_KEY] for row in rows] == ['Server A', 'Server B', 'Server C']


def test_an_unresolvable_id_is_labelled_rather_than_left_bare() -> None:
    """A row naming a deleted object is exactly what a reader needs to see, so it is kept and named."""
    rows = [_row(10), _row(99)]
    manager = _StubObjectsManager({10: 'Server A'})

    _replace_object_ids_with_summaries(rows, OBJECT_KEY, manager)

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

    _replace_object_ids_with_summaries(rows, OBJECT_KEY, manager)

    assert rows[0][OBJECT_KEY] == 'My group'
    assert manager.calls == [[10]]


def test_nothing_is_asked_when_no_row_needs_resolving() -> None:
    """An empty page, or a page of group rows only, must not reach the database at all."""
    rows = [_row('My group', ObjectReferenceType.OBJECT_GROUP), _row(None)]
    manager = _StubObjectsManager({10: 'Server A'})

    _replace_object_ids_with_summaries(rows, OBJECT_KEY, manager)
    _replace_object_ids_with_summaries([], OBJECT_KEY, manager)

    assert len(manager.calls) == 0


def test_the_summary_is_requested_without_the_type_prefix() -> None:
    """The report has its own object_type column, so the summary must not repeat the type."""
    manager = _StubObjectsManager({10: 'Server A'})

    class _Recorder(_StubObjectsManager):
        """Records the with_type flag as well"""

        def __init__(self, summaries: dict[int, str]) -> None:
            super().__init__(summaries)
            self.with_type_flags: list[bool] = []

        def get_summary_lines_lookup(self, object_ids: list[int], with_type: bool = True) -> dict[int, str]:
            """Records the flag, then delegates"""
            self.with_type_flags.append(with_type)

            return super().get_summary_lines_lookup(object_ids, with_type)

    recorder = _Recorder({10: 'Server A'})
    _replace_object_ids_with_summaries([_row(10)], OBJECT_KEY, recorder)

    assert recorder.with_type_flags == [False]
    assert len(manager.calls) == 0
