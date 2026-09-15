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
Unit tests for cmdb.manager.types_mds_helper

Pure tests: no Mongo, no manager. Two questions are asked of this module - what a CmdbType edit
changes in its objects' multi-data sections (`plan_mds_changes`) and what that does to one object
(`apply_plan`) - and three of the answers used to be wrong:

  - **a new field's type came from the OLD type**, which by definition does not contain it, so every
    newly added MDS field was written as `text` whatever it was declared as. The plan now carries a
    field-type map built from the UPDATED type, and the test below declares a `date` for that reason
  - **a removed section was skipped**, so every object kept the rows of a section its type no longer
    declared - invisible to every read and impossible to edit. It is now dropped from the object
  - **an entry was written with enum members as its keys**, so one row held two shapes; `.value` is
    what a stored document carries

The canonical MDS shape nests rows under `section['values'][*]['data']`, each row a list of
`{name, value, type}` entries, and the tests operate on that level rather than on a `data` key placed
directly on the section.
"""
from typing import Any

import pytest

from cmdb.manager.types_mds_helper import (
    MdsChangePlan,
    add_field_entries,
    apply_plan,
    build_field_type_map,
    diff_field_names,
    mds_rows,
    plan_mds_changes,
    remove_field_entries,
    row_entries,
)
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model import CmdbType, FieldKey, FieldType, SectionKey, SectionType, TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42
SECTION_ID: str = 'dg-ipam-interface'
OTHER_SECTION_ID: str = 'dg-other-section'


def _entry(name: str, value: Any = None, field_type: str = FieldType.TEXT.value) -> dict[str, Any]:
    """One stored MDS field entry."""
    return {
        CmdbObjectFieldKey.NAME.value: name,
        CmdbObjectFieldKey.VALUE.value: value,
        CmdbObjectFieldKey.TYPE.value: field_type,
    }


def _section(section_id: str, rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """One MDS section with its rows nested under values[].data."""
    return {
        CmdbObjectMdsKey.SECTION_ID.value: section_id,
        CmdbObjectMdsKey.VALUES.value: [{CmdbObjectMdsRowKey.DATA.value: row} for row in rows],
    }


def _object(sections: list[dict[str, Any]]) -> CmdbObject:
    """A CmdbObject carrying the given MDS sections."""
    return CmdbObject.from_data({
        CmdbObjectKey.PUBLIC_ID.value: 1,
        CmdbObjectKey.TYPE_ID.value: TYPE_ID,
        CmdbObjectKey.AUTHOR_ID.value: 1,
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: sections,
    })


def _names(section: dict[str, Any], row_index: int = 0) -> list[str]:
    """The field names of one row, in order."""
    return [
        entry[CmdbObjectFieldKey.NAME.value]
        for entry in section[CmdbObjectMdsKey.VALUES.value][row_index][CmdbObjectMdsRowKey.DATA.value]
    ]


def _entry_by_name(section: dict[str, Any], name: str, row_index: int = 0) -> dict[str, Any]:
    """One entry of one row, by field name."""
    return next(
        entry
        for entry in section[CmdbObjectMdsKey.VALUES.value][row_index][CmdbObjectMdsRowKey.DATA.value]
        if entry[CmdbObjectFieldKey.NAME.value] == name
    )


def _old_type(section_fields: list[str], section_type: str = SectionType.MDS_SECTION.value) -> CmdbType:
    """A stored CmdbType with one section carrying the given fields."""
    return CmdbType.from_data({
        TypeSchemaKey.PUBLIC_ID.value: TYPE_ID,
        'name': 'a-type',
        TypeSchemaKey.LABEL.value: 'A Type',
        'author_id': 1,
        'version': '1.0.0',
        'active': True,
        TypeSchemaKey.FIELDS.value: [
            {FieldKey.NAME.value: name, FieldKey.TYPE.value: FieldType.TEXT.value}
            for name in section_fields
        ],
        TypeSchemaKey.RENDER_META.value: {
            'icon': 'fa-cube',
            'externals': [],
            'summary': {TypeSchemaKey.FIELDS.value: section_fields},
            TypeSchemaKey.SECTIONS.value: [{
                SectionKey.TYPE.value: section_type,
                SectionKey.NAME.value: SECTION_ID,
                SectionKey.LABEL.value: 'Section',
                SectionKey.FIELDS.value: section_fields,
            }],
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    })


def _updated_doc(
        section_fields: list[str] | None,
        field_types: dict[str, str] | None = None,
        section_type: str = SectionType.MDS_SECTION.value,
) -> dict[str, Any]:
    """An updated-type document; `section_fields=None` removes the section."""
    types: dict[str, str] = field_types or {}
    sections: list[dict[str, Any]] = [] if section_fields is None else [{
        SectionKey.TYPE.value: section_type,
        SectionKey.NAME.value: SECTION_ID,
        SectionKey.FIELDS.value: section_fields,
    }]

    return {
        TypeSchemaKey.FIELDS.value: [
            {FieldKey.NAME.value: name, FieldKey.TYPE.value: types.get(name, FieldType.TEXT.value)}
            for name in (section_fields or [])
        ],
        TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: sections},
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 diff_field_names                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDiffFieldNames:
    """What a section gained and what it lost, in a reproducible order."""

    def test_reports_added_and_removed(self) -> None:
        """Both halves come out of one comparison"""
        assert diff_field_names(['a', 'b'], ['a', 'c']) == (['c'], ['b'])

    def test_both_results_are_sorted(self) -> None:
        """
        The order becomes the order of the appended entries

        A set difference has none, so the same edit produced a differently ordered document each time
        it ran - which also made any test of it order-dependent.
        """
        assert diff_field_names([], ['c', 'a', 'b']) == (['a', 'b', 'c'], [])
        assert diff_field_names(['c', 'a', 'b'], []) == ([], ['a', 'b', 'c'])

    def test_an_unchanged_section_reports_nothing(self) -> None:
        """A reorder is not a change: the comparison is by name, not by position"""
        assert diff_field_names(['a', 'b'], ['b', 'a']) == ([], [])


# -------------------------------------------------------------------------------------------------------------------- #
#                                               build_field_type_map                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildFieldTypeMap:
    """The declared type of each field, which is what a new entry is written with."""

    def test_maps_name_to_type(self) -> None:
        """Straight from the type's own field list"""
        fields = [
            {FieldKey.NAME.value: 'a', FieldKey.TYPE.value: FieldType.TEXT.value},
            {FieldKey.NAME.value: 'b', FieldKey.TYPE.value: FieldType.DATE.value},
        ]

        assert build_field_type_map(fields) == {'a': FieldType.TEXT.value, 'b': FieldType.DATE.value}

    def test_a_field_without_a_type_falls_back_to_text(self) -> None:
        """A drifted declaration still yields a usable entry"""
        assert build_field_type_map([{FieldKey.NAME.value: 'a'}]) == {'a': FieldType.TEXT.value}

    def test_a_field_without_a_name_is_skipped(self) -> None:
        """There is nothing to key it by, and guessing would write an entry nothing reads"""
        assert build_field_type_map([{FieldKey.TYPE.value: FieldType.TEXT.value}]) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 plan_mds_changes                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPlanMdsChanges:
    """What a type edit changes, decided from the two type states alone."""

    def test_an_added_field_is_planned_per_section(self) -> None:
        """Keyed by the section name, which is the objects' section_id"""
        plan = plan_mds_changes(_old_type(['a']), _updated_doc(['a', 'b']))

        assert plan.added_fields == {SECTION_ID: ['b']}
        assert plan.deleted_fields == {}
        assert plan.removed_sections == []

    def test_a_removed_field_is_planned_per_section(self) -> None:
        """The destructive half: the entry has to go from every row"""
        plan = plan_mds_changes(_old_type(['a', 'b']), _updated_doc(['a']))

        assert plan.deleted_fields == {SECTION_ID: ['b']}
        assert plan.added_fields == {}

    def test_the_field_type_comes_from_the_updated_type(self) -> None:
        """
        The bug this pins

        The map used to be built from the OLD type, which cannot contain a newly added field - so the
        fallback was the normal path and every new MDS field was stored as `text`.
        """
        plan = plan_mds_changes(
            _old_type(['a']), _updated_doc(['a', 'b'], {'b': FieldType.DATE.value}),
        )

        assert plan.field_type_map['b'] == FieldType.DATE.value

    def test_a_removed_section_is_planned_for_removal(self) -> None:
        """It used to be skipped, which left the objects carrying it forever"""
        plan = plan_mds_changes(_old_type(['a']), _updated_doc(None))

        assert plan.removed_sections == [SECTION_ID]
        assert not plan.is_empty

    def test_a_payload_without_a_section_list_plans_nothing(self) -> None:
        """
        A malformed payload must not be read as "every section was removed"

        Doing so would drop the MDS rows of every object of the type. A type update always carries
        the whole document, so a missing section list is a broken payload, not an instruction.
        """
        assert plan_mds_changes(_old_type(['a']), {}).is_empty
        assert plan_mds_changes(_old_type(['a']), {TypeSchemaKey.RENDER_META.value: {}}).is_empty

    def test_an_explicitly_empty_section_list_removes_the_section(self) -> None:
        """A payload that says "no sections" is authoritative"""
        plan = plan_mds_changes(
            _old_type(['a']),
            {TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: []}},
        )

        assert plan.removed_sections == [SECTION_ID]

    def test_a_non_mds_section_is_ignored(self) -> None:
        """Only MDS sections store rows per object; a normal section's fields live on the object"""
        plan = plan_mds_changes(
            _old_type(['a'], SectionType.SECTION.value),
            _updated_doc(['a', 'b'], section_type=SectionType.SECTION.value),
        )

        assert plan.is_empty

    def test_a_section_matching_by_name_but_not_by_kind_counts_as_removed(self) -> None:
        """
        Sections are matched on (type, name)

        A name alone could collide with a normal section, and turning an MDS section into a normal one
        does remove the MDS section.
        """
        plan = plan_mds_changes(
            _old_type(['a']), _updated_doc(['a'], section_type=SectionType.SECTION.value),
        )

        assert plan.removed_sections == [SECTION_ID]

    def test_a_malformed_section_entry_is_ignored(self) -> None:
        """A non-dict in the section list does not fail the propagation"""
        plan = plan_mds_changes(
            _old_type(['a']),
            {TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: ['not-a-section']}},
        )

        assert plan.removed_sections == [SECTION_ID]

    def test_an_unchanged_type_plans_nothing(self) -> None:
        """A pure metadata edit must not touch a single object"""
        assert plan_mds_changes(_old_type(['a']), _updated_doc(['a'])).is_empty


class TestThePlansQuestions:
    """The two questions the manager asks a plan before it reads anything."""

    def test_affected_section_ids_covers_all_three_kinds_of_change(self) -> None:
        """An object carrying none of them cannot change, so it is never read"""
        plan = MdsChangePlan(
            added_fields={'a': ['x']},
            deleted_fields={'b': ['y']},
            removed_sections=['c'],
        )

        assert plan.affected_section_ids == ['a', 'b', 'c']

    def test_an_empty_plan_is_empty(self) -> None:
        """Nothing to do means no read and no write at all"""
        assert MdsChangePlan().is_empty


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the row-level transformations                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAddFieldEntries:
    """A newly declared field gets an entry in every row."""

    def test_appends_to_every_row_with_the_declared_type(self) -> None:
        """value None, so the row keeps exactly one entry per declared field"""
        section = _section(SECTION_ID, [[_entry('a', 1)], [_entry('a', 2)]])

        assert add_field_entries(section, ['b'], {'b': FieldType.DATE.value}) is True
        assert _names(section, 0) == ['a', 'b']
        assert _names(section, 1) == ['a', 'b']
        assert _entry_by_name(section, 'b') == {
            CmdbObjectFieldKey.NAME.value: 'b',
            CmdbObjectFieldKey.VALUE.value: None,
            CmdbObjectFieldKey.TYPE.value: FieldType.DATE.value,
        }

    def test_the_entry_keys_are_plain_strings(self) -> None:
        """
        They used to be enum MEMBERS, so one row held two shapes

        It survives BSON because the enums subclass `str`, but `str()` on such a member yields
        'FieldType.TEXT' - the trap this repo has hit before.
        """
        section = _section(SECTION_ID, [[]])

        add_field_entries(section, ['b'], {})

        entry = row_entries(mds_rows(section)[0])[0]
        assert all(isinstance(key, str) and type(key) is str for key in entry)
        assert type(entry[CmdbObjectFieldKey.TYPE.value]) is str

    def test_an_unmapped_field_falls_back_to_text(self) -> None:
        """A field the updated type does not declare at all still yields a usable entry"""
        section = _section(SECTION_ID, [[]])

        add_field_entries(section, ['b'], {})

        assert _entry_by_name(section, 'b')[CmdbObjectFieldKey.TYPE.value] == FieldType.TEXT.value

    def test_an_entry_already_present_is_left_alone(self) -> None:
        """Idempotent, and it reports no change - so a re-run writes nothing"""
        section = _section(SECTION_ID, [[_entry('b', 'kept')]])

        assert add_field_entries(section, ['b'], {'b': FieldType.TEXT.value}) is False
        assert _entry_by_name(section, 'b')[CmdbObjectFieldKey.VALUE.value] == 'kept'

    def test_a_row_without_data_gains_the_key(self) -> None:
        """A drifted row is filled rather than skipped"""
        section = {
            CmdbObjectMdsKey.SECTION_ID.value: SECTION_ID,
            CmdbObjectMdsKey.VALUES.value: [{}],
        }

        assert add_field_entries(section, ['b'], {}) is True
        assert _names(section) == ['b']

    def test_a_section_without_rows_is_a_no_op(self) -> None:
        """Nothing captured yet, nothing to extend"""
        assert add_field_entries(_section(SECTION_ID, []), ['b'], {}) is False


class TestRemoveFieldEntries:
    """A field the type dropped goes from every row."""

    def test_removes_from_every_row(self) -> None:
        """The other rows' values are untouched"""
        section = _section(SECTION_ID, [[_entry('a', 1), _entry('b', 2)], [_entry('a', 3), _entry('b', 4)]])

        assert remove_field_entries(section, ['b']) is True
        assert _names(section, 0) == ['a']
        assert _names(section, 1) == ['a']

    def test_reports_no_change_when_the_field_is_not_in_the_rows(self) -> None:
        """So an object whose rows never carried it is not rewritten"""
        section = _section(SECTION_ID, [[_entry('a', 1)]])

        assert remove_field_entries(section, ['b']) is False

    def test_a_row_without_data_is_skipped(self) -> None:
        """One of the arms no test reached before"""
        section = {
            CmdbObjectMdsKey.SECTION_ID.value: SECTION_ID,
            CmdbObjectMdsKey.VALUES.value: [{}, {CmdbObjectMdsRowKey.DATA.value: [_entry('b')]}],
        }

        assert remove_field_entries(section, ['b']) is True
        assert row_entries(mds_rows(section)[1]) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    apply_plan                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestApplyPlan:
    """One object, in memory, and whether it really changed."""

    def test_applies_the_plan_to_the_matching_section(self) -> None:
        """Sections are matched by the objects' section_id"""
        cmdb_object = _object([_section(SECTION_ID, [[_entry('a')]]), _section(OTHER_SECTION_ID, [[_entry('a')]])])
        plan = MdsChangePlan(added_fields={SECTION_ID: ['b']}, field_type_map={'b': FieldType.DATE.value})

        assert apply_plan(plan, cmdb_object) is True
        assert _names(cmdb_object.multi_data_sections[0]) == ['a', 'b']
        assert _names(cmdb_object.multi_data_sections[1]) == ['a']

    def test_drops_a_removed_section_from_the_object(self) -> None:
        """
        The decision of 2026-09-09: a removed section is removed, not kept silently

        The object stops carrying rows of a section its type does not declare.
        """
        cmdb_object = _object([_section(SECTION_ID, [[_entry('a', 'value')]]),
                               _section(OTHER_SECTION_ID, [[_entry('a')]])])
        plan = MdsChangePlan(removed_sections=[SECTION_ID])

        assert apply_plan(plan, cmdb_object) is True
        assert [section[CmdbObjectMdsKey.SECTION_ID.value]
                for section in cmdb_object.multi_data_sections] == [OTHER_SECTION_ID]

    def test_a_removal_and_a_field_change_apply_together(self) -> None:
        """One edit can remove one section and change another"""
        cmdb_object = _object([_section(SECTION_ID, [[_entry('a')]]),
                               _section(OTHER_SECTION_ID, [[_entry('a'), _entry('gone')]])])
        plan = MdsChangePlan(
            deleted_fields={OTHER_SECTION_ID: ['gone']},
            removed_sections=[SECTION_ID],
        )

        assert apply_plan(plan, cmdb_object) is True
        assert len(cmdb_object.multi_data_sections) == 1
        assert _names(cmdb_object.multi_data_sections[0]) == ['a']

    def test_reports_no_change_for_an_object_the_plan_does_not_touch(self) -> None:
        """Its sections are not in the plan, so it is never written"""
        cmdb_object = _object([_section(OTHER_SECTION_ID, [[_entry('a')]])])
        plan = MdsChangePlan(added_fields={SECTION_ID: ['b']})

        assert apply_plan(plan, cmdb_object) is False
        assert _names(cmdb_object.multi_data_sections[0]) == ['a']

    def test_reports_no_change_when_the_field_is_already_there(self) -> None:
        """Re-running a propagation writes nothing"""
        cmdb_object = _object([_section(SECTION_ID, [[_entry('a'), _entry('b')]])])
        plan = MdsChangePlan(added_fields={SECTION_ID: ['b']}, field_type_map={'b': FieldType.TEXT.value})

        assert apply_plan(plan, cmdb_object) is False

    def test_an_object_without_multi_data_sections_is_a_no_op(self) -> None:
        """Most objects of a type with an MDS section carry none of its rows yet"""
        cmdb_object = _object([])

        assert apply_plan(MdsChangePlan(removed_sections=[SECTION_ID]), cmdb_object) is False


@pytest.mark.parametrize('accessor, expected', [(mds_rows, []), (row_entries, [])],
                         ids=['rows', 'entries'])
def test_the_shape_accessors_answer_empty_for_a_missing_key(accessor: Any, expected: list) -> None:
    """The MDS shape is read in one place, and a drifted document reads as empty rather than raising"""
    assert accessor({}) == expected
