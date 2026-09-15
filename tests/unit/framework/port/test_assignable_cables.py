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
Unit tests for cmdb.framework.port.assignable_cables

Pure tests: no Mongo, no Flask. The module answers two questions and neither of them reads anything -
which Cable CIs a connection may still claim (as criteria the route appends behind the caller's own
``?filter=``) and what one of them looks like in the picker.

What is pinned here: the CABLE type marker is applied even when no type carries it (an installation
with no cable type has nothing to assign, so matching nothing is the answer rather than skipping the
rule), the claimed-cable exclusion is omitted when it would exclude nothing, the ``?search=`` term is
escaped to a literal case-insensitive substring and asked as an ``$elemMatch`` on the ``fields`` entry
carrying the cable name (a dotted path would answer a different question), and a row reports its five
cable values as text with the CmdbType label resolved from the page's lookup.
"""
from typing import Any

import pytest

from cmdb.framework.port.assignable_cables import (
    build_cable_name_search_criteria,
    build_unassigned_cable_criteria,
    build_unassigned_cable_row,
    build_unassigned_cable_rows,
)
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_connection_model import AssignableCableKey
from cmdb.models.special_type_model.cable_constants import CableField
# -------------------------------------------------------------------------------------------------------------------- #

CABLE_TYPE_IDS: list[int] = [11, 12]
CABLE_CI_ID: int = 501
OTHER_CABLE_CI_ID: int = 502
TYPE_ID_KEY: str = CmdbObjectKey.TYPE_ID.value
PUBLIC_ID_KEY: str = CmdbObjectKey.PUBLIC_ID.value
FIELDS_KEY: str = CmdbObjectKey.FIELDS.value
MATCH: str = '$match'
CABLE_TYPE_LABEL: str = 'Cable'


def _cable_doc(public_id: int, type_id: int = 11, **values: Any) -> dict[str, Any]:
    """A CABLE SpecialType CmdbObject document carrying the given dg-cable-* values."""
    return {
        PUBLIC_ID_KEY: public_id,
        TYPE_ID_KEY: type_id,
        CmdbObjectKey.ACTIVE.value: True,
        FIELDS_KEY: [{'name': name, 'value': value, 'type': 'text'} for name, value in values.items()],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                        build_unassigned_cable_criteria                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildUnassignedCableCriteria:
    """The two rules: the CABLE type marker, and every cable another connection already claims."""

    def test_type_marker_is_always_applied(self) -> None:
        """Only objects of a CABLE-marked type are candidates."""
        criteria = build_unassigned_cable_criteria(CABLE_TYPE_IDS, [])

        assert criteria == {TYPE_ID_KEY: {'$in': CABLE_TYPE_IDS}}

    def test_no_cable_type_matches_nothing(self) -> None:
        """An installation whose types carry no CABLE marker has nothing to assign."""
        criteria = build_unassigned_cable_criteria([], [])

        assert criteria == {TYPE_ID_KEY: {'$in': []}}

    def test_claimed_cables_are_excluded(self) -> None:
        """A cable another connection uses is out - the index would refuse it anyway."""
        criteria = build_unassigned_cable_criteria(CABLE_TYPE_IDS, [CABLE_CI_ID, OTHER_CABLE_CI_ID])

        assert criteria[PUBLIC_ID_KEY] == {'$nin': [CABLE_CI_ID, OTHER_CABLE_CI_ID]}
        assert criteria[TYPE_ID_KEY] == {'$in': CABLE_TYPE_IDS}

    def test_empty_exclusion_adds_no_stage(self) -> None:
        """A database without a single cabled connection gets no '$nin' against an empty list."""
        criteria = build_unassigned_cable_criteria(CABLE_TYPE_IDS, [])

        assert PUBLIC_ID_KEY not in criteria


# -------------------------------------------------------------------------------------------------------------------- #
#                                        build_cable_name_search_criteria                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildCableNameSearchCriteria:
    """``?search=`` is a literal, case-insensitive substring match on the cable's name."""

    def test_matches_the_name_field_element(self) -> None:
        """The match is an $elemMatch on the entry carrying dg-cable-name, not a dotted path."""
        criteria = build_cable_name_search_criteria('Patch')

        assert criteria == {
            FIELDS_KEY: {
                '$elemMatch': {
                    'name': CableField.NAME.value,
                    'value': {'$regex': 'Patch', '$options': 'i'},
                }
            }
        }

    def test_term_is_escaped_to_a_literal(self) -> None:
        """A regex metacharacter in a picker's search box is a character, not an operator."""
        criteria = build_cable_name_search_criteria('a.b*')

        assert criteria[FIELDS_KEY]['$elemMatch']['value']['$regex'] == 'a\\.b\\*'

    @pytest.mark.parametrize('search', [None, '', '   '], ids=['none', 'empty', 'whitespace'])
    def test_blank_term_adds_no_criteria(self, search: str | None) -> None:
        """Nothing to search for must not become an empty pattern matching everything."""
        assert build_cable_name_search_criteria(search) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                           build_unassigned_cable_row(s)                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildUnassignedCableRow:
    """One row: the object's identity, its five cable values as text, its CmdbType label."""

    def test_row_carries_the_declared_key_set(self) -> None:
        """The row shape is AssignableCableKey - nothing more, nothing less."""
        row = build_unassigned_cable_row(_cable_doc(CABLE_CI_ID), {11: CABLE_TYPE_LABEL})

        assert set(row) == {key.value for key in AssignableCableKey}

    def test_cable_values_are_read_from_the_fields_triples(self) -> None:
        """The five dg-cable-* values answer the row's cable keys."""
        document = _cable_doc(
            CABLE_CI_ID,
            **{
                CableField.NAME.value: 'Patch 1',
                CableField.TYPE.value: 'CAT6',
                CableField.LENGTH.value: '3m',
                CableField.COLOR.value: 'blue',
                CableField.DESCRIPTION.value: 'rack to switch',
            },
        )

        row = build_unassigned_cable_row(document, {11: CABLE_TYPE_LABEL})

        assert row[AssignableCableKey.PUBLIC_ID.value] == CABLE_CI_ID
        assert row[AssignableCableKey.NAME.value] == 'Patch 1'
        assert row[AssignableCableKey.CABLE_TYPE.value] == 'CAT6'
        assert row[AssignableCableKey.LENGTH.value] == '3m'
        assert row[AssignableCableKey.COLOR.value] == 'blue'
        assert row[AssignableCableKey.DESCRIPTION.value] == 'rack to switch'

    def test_values_are_reported_as_text(self) -> None:
        """An imported numeric cable name renders instead of breaking the page."""
        document = _cable_doc(CABLE_CI_ID, **{CableField.NAME.value: 5})

        row = build_unassigned_cable_row(document, {})

        assert row[AssignableCableKey.NAME.value] == '5'

    def test_missing_values_are_null(self) -> None:
        """A cable whose optional fields were never filled reports them as null."""
        row = build_unassigned_cable_row(_cable_doc(CABLE_CI_ID), {11: CABLE_TYPE_LABEL})

        assert row[AssignableCableKey.NAME.value] is None
        assert row[AssignableCableKey.LENGTH.value] is None

    def test_type_label_is_resolved_from_the_lookup(self) -> None:
        """The row's type_id / type_label describe the Cable CI's CmdbType."""
        row = build_unassigned_cable_row(_cable_doc(CABLE_CI_ID, type_id=12), {12: CABLE_TYPE_LABEL})

        assert row[AssignableCableKey.TYPE_ID.value] == 12
        assert row[AssignableCableKey.TYPE_LABEL.value] == CABLE_TYPE_LABEL

    def test_unresolved_type_keeps_the_row(self) -> None:
        """A cable whose type has gone is still assignable, with a null label rather than no row."""
        row = build_unassigned_cable_row(_cable_doc(CABLE_CI_ID, type_id=99), {11: CABLE_TYPE_LABEL})

        assert row[AssignableCableKey.TYPE_ID.value] == 99
        assert row[AssignableCableKey.TYPE_LABEL.value] is None

    def test_non_integer_type_id_is_not_looked_up(self) -> None:
        """A drifted document whose type_id is not an id reports a null label instead of raising."""
        document = {**_cable_doc(CABLE_CI_ID), TYPE_ID_KEY: 'broken'}

        row = build_unassigned_cable_row(document, {11: CABLE_TYPE_LABEL})

        assert row[AssignableCableKey.TYPE_LABEL.value] is None

    def test_active_flag_is_reported(self) -> None:
        """The picker can tell an inactive cable apart even when it is offered."""
        document = {**_cable_doc(CABLE_CI_ID), CmdbObjectKey.ACTIVE.value: False}

        assert build_unassigned_cable_row(document, {})[AssignableCableKey.ACTIVE.value] is False


class TestBuildUnassignedCableRows:
    """A page of rows keeps the order the aggregation returned."""

    def test_input_order_is_preserved(self) -> None:
        """The caller's ?sort= is applied by the database, so the page is not re-ordered here."""
        documents = [_cable_doc(OTHER_CABLE_CI_ID), _cable_doc(CABLE_CI_ID)]

        rows = build_unassigned_cable_rows(documents, {11: CABLE_TYPE_LABEL})

        assert [row[AssignableCableKey.PUBLIC_ID.value] for row in rows] == [OTHER_CABLE_CI_ID, CABLE_CI_ID]

    def test_empty_page_is_empty(self) -> None:
        """No candidates, no rows."""
        assert build_unassigned_cable_rows([], {}) == []
