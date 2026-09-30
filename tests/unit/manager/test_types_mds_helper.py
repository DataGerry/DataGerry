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
changes in its objects' multi-data sections (`plan_mds_changes`), and which server-side statements
perform that (`build_mds_updates`) - and three of the answers are easy to get wrong:

  - **a new field's type must come from the UPDATED type**, which is the only one that contains it -
    so the test below declares a `date` for the new field, and a declared default for its value
  - **a removed section is removed from the objects**; skipping it would leave every object carrying
    rows of a section its type no longer declares - invisible to every read and impossible to edit
  - **an entry carries `.value` keys**, the shape a stored document has, never enum members

What the statements do to a real collection is pinned in the integration tier; here it is what they ARE.
"""
from typing import Any

from cmdb.manager.objects_propagation_helper import (
    build_add_mds_field_update,
    build_remove_mds_fields_update,
    build_remove_mds_section_update,
)
from cmdb.manager.types_mds_helper import (
    MdsChangePlan,
    build_field_definition_map,
    build_mds_updates,
    build_new_field_entry,
    diff_field_names,
    plan_mds_changes,
)
from cmdb.models.object_model import CmdbObjectFieldKey
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
        field_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An updated-type document; `section_fields=None` removes the section."""
    types: dict[str, str] = field_types or {}
    defaults: dict[str, Any] = field_defaults or {}
    sections: list[dict[str, Any]] = [] if section_fields is None else [{
        SectionKey.TYPE.value: section_type,
        SectionKey.NAME.value: SECTION_ID,
        SectionKey.FIELDS.value: section_fields,
    }]

    return {
        TypeSchemaKey.FIELDS.value: [
            {
                FieldKey.NAME.value: name,
                FieldKey.TYPE.value: types.get(name, FieldType.TEXT.value),
                **({FieldKey.VALUE.value: defaults[name]} if name in defaults else {}),
            }
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
#                                             build_field_definition_map                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildFieldDefinitionMap:
    """The declaration of each field, which is what a new entry is built from."""

    def test_maps_name_to_definition(self) -> None:
        """Straight from the type's own field list, the whole definition"""
        date_field: dict[str, Any] = {FieldKey.NAME.value: 'b', FieldKey.TYPE.value: FieldType.DATE.value}

        assert build_field_definition_map([date_field]) == {'b': date_field}

    def test_a_field_without_a_name_is_skipped(self) -> None:
        """There is nothing to key it by, and guessing would write an entry nothing reads"""
        assert build_field_definition_map([{FieldKey.TYPE.value: FieldType.TEXT.value}]) == {}

    def test_a_field_that_is_not_a_mapping_is_skipped(self) -> None:
        """A drifted field list does not fail the propagation"""
        assert build_field_definition_map(['not-a-field']) == {}


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

    def test_the_field_definitions_come_from_the_updated_type(self) -> None:
        """
        Only the updated type can describe a newly added field

        A map built from the stored type would lack it, and the new entry would fall back to an
        empty `text` entry whatever the field was declared as.
        """
        plan = plan_mds_changes(
            _old_type(['a']), _updated_doc(['a', 'b'], {'b': FieldType.DATE.value}),
        )

        assert plan.field_definitions['b'][FieldKey.TYPE.value] == FieldType.DATE.value

    def test_a_removed_section_is_planned_for_removal(self) -> None:
        """Skipping it leaves the objects carrying it forever"""
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


def test_an_empty_plan_is_empty() -> None:
    """Nothing to do means no statement at all"""
    assert MdsChangePlan().is_empty


# -------------------------------------------------------------------------------------------------------------------- #
#                                               build_new_field_entry                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildNewFieldEntry:
    """The entry every existing row gets for a newly added field."""

    def test_carries_the_declared_type_and_default(self) -> None:
        """The definition decides both, so a new row entry matches what a new object would hold"""
        plan = plan_mds_changes(
            _old_type(['a']),
            _updated_doc(['a', 'b'], {'b': FieldType.DATE.value}, field_defaults={'b': '2026-01-01'}),
        )

        assert build_new_field_entry(plan, 'b') == _entry('b', '2026-01-01', FieldType.DATE.value)

    def test_without_a_default_the_value_is_none(self) -> None:
        """A field that declares no default starts empty"""
        plan = plan_mds_changes(_old_type(['a']), _updated_doc(['a', 'b']))

        assert build_new_field_entry(plan, 'b') == _entry('b')

    def test_an_undeclared_name_is_an_empty_text_entry(self) -> None:
        """A section may list a name the field list lacks; the row still gets one entry for it"""
        assert build_new_field_entry(MdsChangePlan(), 'ghost') == _entry('ghost')

    def test_the_entry_carries_plain_string_keys(self) -> None:
        """The shape a stored document has - enum members as keys would give one row two shapes"""
        entry = build_new_field_entry(MdsChangePlan(), 'x')

        assert all(type(key) is str for key in entry)  # pylint: disable=unidiomatic-typecheck
        assert set(entry) == {
            CmdbObjectFieldKey.NAME.value, CmdbObjectFieldKey.VALUE.value, CmdbObjectFieldKey.TYPE.value,
        }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 build_mds_updates                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildMdsUpdates:
    """The statements a plan becomes - one per added field, one per section losing fields or going."""

    def test_an_added_field_is_one_push_per_field(self) -> None:
        """Each new field is pushed into the rows of its section, carrying its declared entry"""
        plan = plan_mds_changes(_old_type(['a']), _updated_doc(['a', 'b', 'c']))

        assert build_mds_updates(TYPE_ID, plan) == [
            build_add_mds_field_update(TYPE_ID, SECTION_ID, _entry('b')),
            build_add_mds_field_update(TYPE_ID, SECTION_ID, _entry('c')),
        ]

    def test_removed_fields_are_one_pull_per_section(self) -> None:
        """All the fields a section lost go in a single statement"""
        plan = plan_mds_changes(_old_type(['a', 'b', 'c']), _updated_doc(['a']))

        assert build_mds_updates(TYPE_ID, plan) == [build_remove_mds_fields_update(TYPE_ID, SECTION_ID, ['b', 'c'])]

    def test_a_removed_section_is_one_pull_of_the_section(self) -> None:
        """The whole section goes, with all of its rows"""
        plan = plan_mds_changes(_old_type(['a']), _updated_doc(None))

        assert build_mds_updates(TYPE_ID, plan) == [build_remove_mds_section_update(TYPE_ID, SECTION_ID)]

    def test_an_empty_plan_issues_nothing(self) -> None:
        """A metadata edit writes no object"""
        assert build_mds_updates(TYPE_ID, MdsChangePlan()) == []

    def test_the_order_is_deterministic(self) -> None:
        """Adds, then field removals, then section removals - each by sorted section id"""
        plan = MdsChangePlan(
            added_fields={'z': ['n'], 'a': ['m']},
            deleted_fields={'y': ['p'], 'b': ['q']},
            removed_sections=['x', 'c'],
        )

        assert build_mds_updates(TYPE_ID, plan) == [
            build_add_mds_field_update(TYPE_ID, 'a', _entry('m')),
            build_add_mds_field_update(TYPE_ID, 'z', _entry('n')),
            build_remove_mds_fields_update(TYPE_ID, 'b', ['q']),
            build_remove_mds_fields_update(TYPE_ID, 'y', ['p']),
            build_remove_mds_section_update(TYPE_ID, 'c'),
            build_remove_mds_section_update(TYPE_ID, 'x'),
        ]
