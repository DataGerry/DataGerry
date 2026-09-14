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
Unit tests for the CmdbType reference-section dependency helpers

A ref-section resolves its target BY NAME at render time, so nothing in the database ties the two
types together - which is why every question here is answered by querying the dependents and reading
their own reference entries. The two properties under test are that the query matches the right
documents (`$elemMatch`, not two dotted paths that different array elements can satisfy between them)
and that an edit is refused when it would leave a dependent showing nothing.

Pure: the TypesManager is a MagicMock and every dependent is handed in as the projected document the
real query would return.
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.type_model import SectionType, TypeSchemaKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_reference_section_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    build_referenced_section_usage_payload,
    describe_section_dependents,
    get_own_referenced_section_names,
    get_own_section_references,
    get_removed_section_names,
    get_section_field_names,
    get_section_reference_selections,
    get_types_referencing_section,
    guard_referenced_section_removal,
    referenced_section_field_removal_blocker,
    referenced_section_removal_blocker,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    ReferencedSectionUsageKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper'

HTTP_BAD_REQUEST: int = 400


def _patch_managers_by_type(managers: dict) -> Any:
    """Patches ManagerProvider.get_manager to return the mock registered for each ManagerType."""
    return patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: managers[mtype])


# ------------------------------------------ referenced-section removal guard ---------------------------------------- #

USER_TYPE_ID: int = 900
DEPENDENT_TYPE_ID: int = 901
REFERENCED_SECTION: str = 'personal-data'
OTHER_SECTION: str = 'other'


def _dependent(public_id: int = DEPENDENT_TYPE_ID, name: str = 'test', label: str | None = 'test') -> dict[str, Any]:
    """One dependent type as the projected lookup returns it."""
    return {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.NAME.value: name,
        TypeSchemaKey.LABEL.value: label,
    }


def _types_manager(found: list[dict[str, Any]] | None = None) -> MagicMock:
    """A TypesManager stand-in whose find() returns the given dependents."""
    manager = MagicMock()
    manager.find.return_value = found or []

    return manager


def _section(name: str, section_type: str = SectionType.SECTION.value) -> SimpleNamespace:
    """A plain section stand-in."""
    return SimpleNamespace(name=name, type=section_type)


def _type_with_sections(*sections: Any, public_id: int = USER_TYPE_ID,
                        name: str = 'User', label: str = 'User') -> SimpleNamespace:
    """A CmdbType stand-in exposing only get_sections() / get_public_id() / name / label."""
    return SimpleNamespace(
        get_sections=lambda: list(sections),
        get_public_id=lambda: public_id,
        name=name,
        label=label,
    )


def _ref_section(name: str, type_id: int, section_name: str) -> Any:
    """A real TypeReferenceSection, so the blocker's isinstance check is exercised."""
    return types_reference_section_helper.TypeReferenceSection.from_data({
        SectionKey.TYPE.value: SectionType.REF_SECTION.value,
        SectionKey.NAME.value: name,
        SectionKey.LABEL.value: name,
        SectionKey.REFERENCE.value: {
            SectionReferenceKey.TYPE_ID.value: type_id,
            SectionReferenceKey.SECTION_NAME.value: section_name,
            SectionReferenceKey.SELECTED_FIELDS.value: [],
        },
        SectionKey.FIELDS.value: [],
    })


class TestGetTypesReferencingSection:
    """The dependent lookup."""

    def test_matches_the_section_list_with_elem_match(self) -> None:
        """
        Two dotted paths would be satisfied by DIFFERENT array elements

        A type carrying any ref-section plus an unrelated section that names this type_id would then
        match, and be refused for a dependency it does not have.
        """
        types = _types_manager()

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            get_types_referencing_section(MagicMock(), USER_TYPE_ID, REFERENCED_SECTION)

        criteria = types.find.call_args.kwargs['criteria']
        sections_key = f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}'
        element_match = criteria[sections_key]['$elemMatch']

        assert element_match[SectionKey.TYPE.value] == SectionType.REF_SECTION.value
        assert element_match[
            f'{SectionKey.REFERENCE.value}.{SectionReferenceKey.TYPE_ID.value}'
        ] == USER_TYPE_ID
        assert element_match[
            f'{SectionKey.REFERENCE.value}.{SectionReferenceKey.SECTION_NAME.value}'
        ] == REFERENCED_SECTION

    def test_without_a_section_name_matches_any_reference_to_the_type(self) -> None:
        """The type-deletion check asks 'is this type referenced at all'"""
        types = _types_manager()

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            get_types_referencing_section(MagicMock(), USER_TYPE_ID)

        sections_key = f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}'
        element_match = types.find.call_args.kwargs['criteria'][sections_key]['$elemMatch']

        assert f'{SectionKey.REFERENCE.value}.{SectionReferenceKey.SECTION_NAME.value}' not in element_match

    def test_excludes_the_given_type(self) -> None:
        """The type being written is excluded - its own sections come from the payload, not the DB"""
        types = _types_manager()

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            get_types_referencing_section(MagicMock(), USER_TYPE_ID, exclude_type_id=USER_TYPE_ID)

        assert types.find.call_args.kwargs['criteria'][TypeSchemaKey.PUBLIC_ID.value] == {'$ne': USER_TYPE_ID}

    def test_no_exclusion_leaves_the_public_id_unfiltered(self) -> None:
        """Without an exclusion the query carries no public_id condition at all"""
        types = _types_manager()

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            get_types_referencing_section(MagicMock(), USER_TYPE_ID)

        assert TypeSchemaKey.PUBLIC_ID.value not in types.find.call_args.kwargs['criteria']

    def test_projects_the_identity_and_drops_the_object_id(self) -> None:
        """
        These dicts go into a REST response, where an ObjectId is not serialisable

        dbm.find only excludes '_id' when NO projection is passed, so it has to be excluded here.
        """
        types = _types_manager()

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            get_types_referencing_section(MagicMock(), USER_TYPE_ID)

        projection = types.find.call_args.kwargs['projection']

        assert projection['_id'] == 0
        assert set(projection) == {'_id', TypeSchemaKey.PUBLIC_ID.value,
                                   TypeSchemaKey.NAME.value, TypeSchemaKey.LABEL.value}


class TestGetRemovedSectionNames:
    """Which sections an update drops."""

    def test_reports_a_removed_section(self) -> None:
        """The straightforward case"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION), _section(OTHER_SECTION))
        new_type = _type_with_sections(_section(OTHER_SECTION))

        assert get_removed_section_names(old_type, new_type) == {REFERENCED_SECTION}

    def test_reports_nothing_when_the_sections_are_unchanged(self) -> None:
        """An unrelated edit costs no lookup"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        new_type = _type_with_sections(_section(REFERENCED_SECTION))

        assert get_removed_section_names(old_type, new_type) == set()

    def test_a_rename_counts_as_a_removal(self) -> None:
        """A ref-section resolves its target by NAME, so a rename breaks it exactly as a delete does"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        new_type = _type_with_sections(_section('renamed'))

        assert get_removed_section_names(old_type, new_type) == {REFERENCED_SECTION}

    def test_an_added_section_is_not_a_removal(self) -> None:
        """Additions are never destructive"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        new_type = _type_with_sections(_section(REFERENCED_SECTION), _section(OTHER_SECTION))

        assert get_removed_section_names(old_type, new_type) == set()


class TestGetOwnReferencedSectionNames:
    """The self-referencing case, which cannot be read from the database during an update."""

    def test_finds_a_self_reference(self) -> None:
        """A type may hold a ref-section aimed at its own sections"""
        type_instance = _type_with_sections(
            _section(REFERENCED_SECTION),
            _ref_section('self-ref', USER_TYPE_ID, REFERENCED_SECTION),
        )

        assert get_own_referenced_section_names(type_instance, USER_TYPE_ID) == {REFERENCED_SECTION}

    def test_ignores_a_reference_to_another_type(self) -> None:
        """Only references aimed at the given type_id count"""
        type_instance = _type_with_sections(_ref_section('other-ref', 12345, REFERENCED_SECTION))

        assert get_own_referenced_section_names(type_instance, USER_TYPE_ID) == set()

    def test_ignores_plain_sections(self) -> None:
        """A plain section carries no reference at all"""
        type_instance = _type_with_sections(_section(REFERENCED_SECTION))

        assert get_own_referenced_section_names(type_instance, USER_TYPE_ID) == set()


class TestDescribeSectionDependents:
    """How a dependent is named in the refusal."""

    def test_names_the_label_and_the_id(self) -> None:
        """The message has to be actionable: which type, and where to find it"""
        assert describe_section_dependents([_dependent()]) == f"'test' (ID:{DEPENDENT_TYPE_ID})"

    def test_falls_back_to_the_name_without_a_label(self) -> None:
        """A type with no label still has to be identifiable"""
        assert describe_section_dependents([_dependent(label=None)]) == f"'test' (ID:{DEPENDENT_TYPE_ID})"

    def test_joins_several_dependents(self) -> None:
        """Every blocking type is listed, not just the first"""
        described = describe_section_dependents([_dependent(), _dependent(902, 'second', 'Second')])

        assert described == f"'test' (ID:{DEPENDENT_TYPE_ID}), 'Second' (ID:902)"


class TestReferencedSectionRemovalBlocker:
    """The rule itself."""

    def test_allows_an_update_that_removes_no_section(self) -> None:
        """No removal, no lookup"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        types = _types_manager([_dependent()])

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            assert referenced_section_removal_blocker(MagicMock(), old_type, old_type) is None

        types.find.assert_not_called()

    def test_allows_removing_a_section_nothing_references(self) -> None:
        """Only referenced sections are protected"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION), _section(OTHER_SECTION))
        new_type = _type_with_sections(_section(REFERENCED_SECTION))

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            assert referenced_section_removal_blocker(MagicMock(), old_type, new_type) is None

    def test_refuses_removing_a_referenced_section(self) -> None:
        """The bug this guard exists for: the dependent would be left pointing at nothing"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        new_type = _type_with_sections()

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent()])}):
            blocker = referenced_section_removal_blocker(MagicMock(), old_type, new_type)

        assert blocker is not None
        assert REFERENCED_SECTION in blocker
        assert f'ID:{DEPENDENT_TYPE_ID}' in blocker

    def test_names_every_blocked_section(self) -> None:
        """An update removing two referenced sections reports both, not the first"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION), _section(OTHER_SECTION))
        new_type = _type_with_sections()

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent()])}):
            blocker = referenced_section_removal_blocker(MagicMock(), old_type, new_type)

        assert REFERENCED_SECTION in blocker
        assert OTHER_SECTION in blocker

    def test_refuses_a_self_reference_that_survives_the_update(self) -> None:
        """
        A type's own ref-section counts as a dependent

        It cannot be read from the database here - the payload is replacing this type's sections - so
        it is judged against the NEW type.
        """
        old_type = _type_with_sections(
            _section(REFERENCED_SECTION),
            _ref_section('self-ref', USER_TYPE_ID, REFERENCED_SECTION),
        )
        new_type = _type_with_sections(_ref_section('self-ref', USER_TYPE_ID, REFERENCED_SECTION))

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            blocker = referenced_section_removal_blocker(MagicMock(), old_type, new_type)

        assert blocker is not None
        assert f'ID:{USER_TYPE_ID}' in blocker

    def test_allows_removing_a_section_and_its_own_reference_together(self) -> None:
        """
        The case a naive guard would break

        One PUT that drops both the section and the ref-section pointing at it leaves nothing
        dangling, so it has to be allowed - which is why the stored copy of this type is excluded
        from the lookup and the self-reference is read from the new payload.
        """
        old_type = _type_with_sections(
            _section(REFERENCED_SECTION),
            _ref_section('self-ref', USER_TYPE_ID, REFERENCED_SECTION),
        )
        new_type = _type_with_sections()

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            assert referenced_section_removal_blocker(MagicMock(), old_type, new_type) is None

    def test_the_lookup_excludes_the_type_being_written(self) -> None:
        """Its stored sections are stale by definition during its own update"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        new_type = _type_with_sections()
        types = _types_manager()

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            referenced_section_removal_blocker(MagicMock(), old_type, new_type)

        assert types.find.call_args.kwargs['criteria'][TypeSchemaKey.PUBLIC_ID.value] == {'$ne': USER_TYPE_ID}


class TestGuardReferencedSectionRemoval:
    """The route-level wrapper."""

    def test_aborts_400_when_the_removal_is_refused(self) -> None:
        """400 is the codebase's business-rule rejection, not 409"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        new_type = _type_with_sections()

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent()])}):
            with pytest.raises(HTTPException) as exc_info:
                guard_referenced_section_removal(MagicMock(), old_type, new_type)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_passes_when_the_removal_is_allowed(self) -> None:
        """An allowed update must not raise"""
        old_type = _type_with_sections(_section(REFERENCED_SECTION))
        new_type = _type_with_sections()

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            guard_referenced_section_removal(MagicMock(), old_type, new_type)  # must not raise


class TestBuildReferencedSectionUsagePayload:
    """The pre-check payload."""

    def test_reports_the_referencing_types_and_the_blocked_sections(self) -> None:
        """
        The frontend needs both halves: may I delete the type, and may I delete THIS section

        The dependent references one of the target's two sections, so only that one is blocked - an
        assertion the per-section query loop this replaced could not make, because the stubbed manager
        answered every section's query with the same dependent.
        """
        target = _type_with_sections(_section(REFERENCED_SECTION), _section(OTHER_SECTION))

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent_doc([])])}):
            payload = build_referenced_section_usage_payload(MagicMock(), target)

        assert payload[ReferencedSectionUsageKey.IN_USE.value] is True
        assert payload[ReferencedSectionUsageKey.COUNT.value] == 1
        assert payload[ReferencedSectionUsageKey.REFERENCING_TYPE_IDS.value] == [DEPENDENT_TYPE_ID]
        assert set(payload[ReferencedSectionUsageKey.SECTIONS.value]) == {REFERENCED_SECTION}

    def test_the_whole_payload_costs_one_query(self) -> None:
        """
        One read, however many sections the type has

        It used to ask the database once per section on top of the initial lookup, on a route the type
        builder calls before every section delete.
        """
        target = _type_with_sections(*[_section(f'section-{index}') for index in range(20)])
        manager = _types_manager([_dependent_doc([])])

        with _patch_managers_by_type({ManagerType.TYPES: manager}):
            build_referenced_section_usage_payload(MagicMock(), target)

        assert manager.find.call_count == 1

    def test_a_reference_without_a_section_name_is_attributed_to_none(self) -> None:
        """
        A ref-section that names a type but no section blocks nothing per section

        `section_name` became required later than the reference itself, so a document written before
        that carries the type id alone - it still counts as a dependent of the TYPE.
        """
        target = _type_with_sections(_section(REFERENCED_SECTION))
        nameless = _dependent_doc([])
        nameless[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.SECTIONS.value][1][
            SectionKey.REFERENCE.value].pop(SectionReferenceKey.SECTION_NAME.value)

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([nameless])}):
            payload = build_referenced_section_usage_payload(MagicMock(), target)

        assert payload[ReferencedSectionUsageKey.IN_USE.value] is True
        assert payload[ReferencedSectionUsageKey.SECTIONS.value] == {}

    def test_a_dependent_referencing_a_section_that_is_gone_is_still_counted(self) -> None:
        """
        Data from before the guard: referenced as a type, attributed to no section of it

        Nothing may be deleted on its account section-wise, but the type itself is still in use.
        """
        target = _type_with_sections(_section(OTHER_SECTION))

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent_doc([])])}):
            payload = build_referenced_section_usage_payload(MagicMock(), target)

        assert payload[ReferencedSectionUsageKey.IN_USE.value] is True
        assert OTHER_SECTION not in payload[ReferencedSectionUsageKey.SECTIONS.value]

    def test_reports_an_unreferenced_type_as_free(self) -> None:
        """Nothing referenced means every section is free to remove"""
        target = _type_with_sections(_section(REFERENCED_SECTION))

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            payload = build_referenced_section_usage_payload(MagicMock(), target)

        assert payload[ReferencedSectionUsageKey.IN_USE.value] is False
        assert payload[ReferencedSectionUsageKey.COUNT.value] == 0
        assert not payload[ReferencedSectionUsageKey.SECTIONS.value]


# -------------------------------------- referenced-section EMPTYING guard (C) --------------------------------------- #

FIELD_A: str = 'field-a'
FIELD_B: str = 'field-b'


def _section_with_fields(name: str, field_names: list[str]) -> SimpleNamespace:
    """A plain section stand-in carrying a field list."""
    return SimpleNamespace(name=name, type=SectionType.SECTION.value, fields=list(field_names))


def _ref_section_with_selection(name: str, type_id: int, section_name: str,
                                selected_fields: list[str]) -> Any:
    """A real TypeReferenceSection carrying a selection."""
    return types_reference_section_helper.TypeReferenceSection.from_data({
        SectionKey.TYPE.value: SectionType.REF_SECTION.value,
        SectionKey.NAME.value: name,
        SectionKey.LABEL.value: name,
        SectionKey.REFERENCE.value: {
            SectionReferenceKey.TYPE_ID.value: type_id,
            SectionReferenceKey.SECTION_NAME.value: section_name,
            SectionReferenceKey.SELECTED_FIELDS.value: list(selected_fields),
        },
        SectionKey.FIELDS.value: [],
    })


def _dependent_doc(selected_fields: list[str], section_name: str = REFERENCED_SECTION,
                   public_id: int = DEPENDENT_TYPE_ID) -> dict[str, Any]:
    """A dependent type document as the sections-projected lookup returns it."""
    return {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.NAME.value: 'test',
        TypeSchemaKey.LABEL.value: 'test',
        TypeSchemaKey.RENDER_META.value: {
            TypeSchemaKey.SECTIONS.value: [
                {SectionKey.TYPE.value: SectionType.SECTION.value, SectionKey.NAME.value: 'own',
                 SectionKey.FIELDS.value: []},
                {SectionKey.TYPE.value: SectionType.REF_SECTION.value,
                 SectionKey.NAME.value: 'the-ref',
                 SectionKey.REFERENCE.value: {
                     SectionReferenceKey.TYPE_ID.value: USER_TYPE_ID,
                     SectionReferenceKey.SECTION_NAME.value: section_name,
                     SectionReferenceKey.SELECTED_FIELDS.value: list(selected_fields),
                 }},
            ],
        },
    }


class TestGetSectionFieldNames:
    """The per-section field lists an update is compared on."""

    def test_maps_every_section_to_its_fields(self) -> None:
        """Both halves of the comparison come from here"""
        type_instance = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, [FIELD_A, FIELD_B]),
            _section_with_fields(OTHER_SECTION, []),
        )

        assert get_section_field_names(type_instance) == {
            REFERENCED_SECTION: [FIELD_A, FIELD_B],
            OTHER_SECTION: [],
        }

    def test_a_section_without_a_field_list_reads_as_empty(self) -> None:
        """A ref-section carries no fields of its own, and must not raise here"""
        type_instance = _type_with_sections(_section(REFERENCED_SECTION))

        assert get_section_field_names(type_instance) == {REFERENCED_SECTION: []}


class TestGetSectionReferenceSelections:
    """The lookup that also reads the dependents' selections."""

    def test_projects_the_sections_as_well_as_the_identity(self) -> None:
        """Deciding whether a dependent would show nothing needs its selection"""
        types = _types_manager()

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            get_section_reference_selections(MagicMock(), USER_TYPE_ID, REFERENCED_SECTION)

        projection = types.find.call_args.kwargs['projection']
        sections_path = f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}'

        assert projection[sections_path] == 1
        assert projection['_id'] == 0

    def test_returns_the_selection_of_the_matching_section_only(self) -> None:
        """
        The query matched the DOCUMENT, so which section matched is re-established in Python

        A dependent's other sections - including a plain section that happens to carry a reference
        dict - must not contribute a selection.
        """
        types = _types_manager([_dependent_doc([FIELD_A])])

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            selections = get_section_reference_selections(MagicMock(), USER_TYPE_ID, REFERENCED_SECTION)

        assert len(selections) == 1
        assert selections[0][SectionReferenceKey.SELECTED_FIELDS.value] == [FIELD_A]
        assert selections[0][TypeSchemaKey.PUBLIC_ID.value] == DEPENDENT_TYPE_ID

    def test_ignores_a_reference_to_another_section_of_the_same_type(self) -> None:
        """Only the section being edited is relevant"""
        types = _types_manager([_dependent_doc([FIELD_A], section_name=OTHER_SECTION)])

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            assert not get_section_reference_selections(MagicMock(), USER_TYPE_ID, REFERENCED_SECTION)

    def test_an_absent_selection_reads_as_unlimited(self) -> None:
        """A stored reference without the key means 'all fields', not 'no fields'"""
        document = _dependent_doc([])
        del document[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.SECTIONS.value][1][
            SectionKey.REFERENCE.value][SectionReferenceKey.SELECTED_FIELDS.value]
        types = _types_manager([document])

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            selections = get_section_reference_selections(MagicMock(), USER_TYPE_ID, REFERENCED_SECTION)

        assert selections[0][SectionReferenceKey.SELECTED_FIELDS.value] == []

    def test_tolerates_a_document_without_render_meta(self) -> None:
        """A malformed type must not take the guard down with it"""
        types = _types_manager([{TypeSchemaKey.PUBLIC_ID.value: DEPENDENT_TYPE_ID}])

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            assert not get_section_reference_selections(MagicMock(), USER_TYPE_ID, REFERENCED_SECTION)


class TestGetOwnSectionReferences:
    """The Type's own reference sections, read from the payload."""

    def test_returns_the_section_name_and_the_selection(self) -> None:
        """The self-reference needs both halves for the emptying check"""
        type_instance = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, [FIELD_A]),
            _ref_section_with_selection('self-ref', USER_TYPE_ID, REFERENCED_SECTION, [FIELD_A]),
        )

        assert get_own_section_references(type_instance, USER_TYPE_ID) == [{
            SectionReferenceKey.SECTION_NAME.value: REFERENCED_SECTION,
            SectionReferenceKey.SELECTED_FIELDS.value: [FIELD_A],
        }]

    def test_the_name_only_wrapper_still_works(self) -> None:
        """get_own_referenced_section_names is now derived from this, and keeps its contract"""
        type_instance = _type_with_sections(
            _ref_section_with_selection('self-ref', USER_TYPE_ID, REFERENCED_SECTION, []),
        )

        assert get_own_referenced_section_names(type_instance, USER_TYPE_ID) == {REFERENCED_SECTION}


class TestReferencedSectionFieldRemovalBlocker:
    """
    Refuse only the edits that leave a dependent with nothing to show

    The rows here are the measured render outcomes: every configuration that renders an EMPTY block
    is refused, every configuration that still renders something is allowed.
    """

    @staticmethod
    def _run(selected_fields: list[str], before: list[str], after: list[str],
             dependents: list[dict[str, Any]] | None = None) -> str | None:
        """Runs the blocker for one section whose fields change from 'before' to 'after'."""
        old_type = _type_with_sections(_section_with_fields(REFERENCED_SECTION, before))
        new_type = _type_with_sections(_section_with_fields(REFERENCED_SECTION, after))
        found = dependents if dependents is not None else [_dependent_doc(selected_fields)]

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager(found)}):
            return referenced_section_field_removal_blocker(MagicMock(), old_type, new_type)

    def test_refuses_taking_the_only_selected_field(self) -> None:
        """The field-side version of the reported bug: the block renders empty"""
        blocker = self._run([FIELD_A], [FIELD_A], [])

        assert blocker is not None
        assert REFERENCED_SECTION in blocker
        assert f'ID:{DEPENDENT_TYPE_ID}' in blocker

    def test_allows_a_partial_reduction(self) -> None:
        """
        Losing the column of a deleted field is the direct consequence of deleting it

        Refusing this would make every field removal on a referenced type a 400.
        """
        assert self._run([FIELD_A, FIELD_B], [FIELD_A, FIELD_B], [FIELD_B]) is None

    def test_refuses_taking_the_last_of_several_selected_fields(self) -> None:
        """Two selected fields removed at once still ends with nothing to show"""
        assert self._run([FIELD_A, FIELD_B], [FIELD_A, FIELD_B], []) is not None

    def test_allows_emptying_a_section_no_reference_uses(self) -> None:
        """Only referenced sections are protected"""
        assert self._run([], [FIELD_A], [], dependents=[]) is None

    def test_refuses_emptying_a_section_an_unlimited_reference_uses(self) -> None:
        """
        The case a 'did we delete a selected field' check would miss entirely

        An unlimited reference stores NO field name, so there is nothing stale to detect - but
        emptying the section blanks it just the same.
        """
        assert self._run([], [FIELD_A], []) is not None

    def test_allows_reducing_a_section_an_unlimited_reference_uses(self) -> None:
        """One field fewer is one column fewer, not a blank block"""
        assert self._run([], [FIELD_A, FIELD_B], [FIELD_B]) is None

    def test_refuses_moving_the_only_selected_field_out_of_the_section(self) -> None:
        """
        The trigger is a field leaving the SECTION, not the type

        A field moved to a sibling section still exists, and the dependent still shows nothing.
        """
        old_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, [FIELD_A]),
            _section_with_fields(OTHER_SECTION, []),
        )
        new_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, []),
            _section_with_fields(OTHER_SECTION, [FIELD_A]),
        )

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent_doc([FIELD_A])])}):
            assert referenced_section_field_removal_blocker(MagicMock(), old_type, new_type) is not None

    def test_allows_an_update_that_changes_no_section_field_list(self) -> None:
        """An unrelated edit costs no lookup at all"""
        old_type = _type_with_sections(_section_with_fields(REFERENCED_SECTION, [FIELD_A]))
        types = _types_manager([_dependent_doc([FIELD_A])])

        with _patch_managers_by_type({ManagerType.TYPES: types}):
            assert referenced_section_field_removal_blocker(MagicMock(), old_type, old_type) is None

        types.find.assert_not_called()

    def test_does_not_protect_a_section_that_already_showed_nothing(self) -> None:
        """
        An already-broken configuration must not block unrelated edits

        The dependent selects a field the section never had, so it showed nothing before the update
        too - there is nothing left to lose.
        """
        assert self._run(['never-there'], [FIELD_A], []) is None

    def test_skips_a_removed_section(self) -> None:
        """A removed section is the other blocker's business, not this one's"""
        old_type = _type_with_sections(_section_with_fields(REFERENCED_SECTION, [FIELD_A]))
        new_type = _type_with_sections()

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent_doc([FIELD_A])])}):
            assert referenced_section_field_removal_blocker(MagicMock(), old_type, new_type) is None

    def test_refuses_a_self_reference_that_would_show_nothing(self) -> None:
        """A Type's own reference section counts, read from the payload"""
        old_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, [FIELD_A]),
            _ref_section_with_selection('self-ref', USER_TYPE_ID, REFERENCED_SECTION, [FIELD_A]),
        )
        new_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, []),
            _ref_section_with_selection('self-ref', USER_TYPE_ID, REFERENCED_SECTION, [FIELD_A]),
        )

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            blocker = referenced_section_field_removal_blocker(MagicMock(), old_type, new_type)

        assert blocker is not None
        assert f'ID:{USER_TYPE_ID}' in blocker

    def test_an_own_reference_to_another_section_is_not_a_dependent(self) -> None:
        """A self-reference aimed at a different section says nothing about the one being edited"""
        old_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, [FIELD_A]),
            _section_with_fields(OTHER_SECTION, [FIELD_B]),
            _ref_section_with_selection('self-ref', USER_TYPE_ID, OTHER_SECTION, [FIELD_B]),
        )
        new_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, []),
            _section_with_fields(OTHER_SECTION, [FIELD_B]),
            _ref_section_with_selection('self-ref', USER_TYPE_ID, OTHER_SECTION, [FIELD_B]),
        )

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            assert referenced_section_field_removal_blocker(MagicMock(), old_type, new_type) is None

    def test_allows_emptying_a_section_whose_own_reference_goes_too(self) -> None:
        """Dropping both sides in one update leaves nothing dangling"""
        old_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, [FIELD_A]),
            _ref_section_with_selection('self-ref', USER_TYPE_ID, REFERENCED_SECTION, [FIELD_A]),
        )
        new_type = _type_with_sections(_section_with_fields(REFERENCED_SECTION, []))

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager()}):
            assert referenced_section_field_removal_blocker(MagicMock(), old_type, new_type) is None

    def test_names_every_blocked_section(self) -> None:
        """An update emptying two referenced sections reports both"""
        old_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, [FIELD_A]),
            _section_with_fields(OTHER_SECTION, [FIELD_B]),
        )
        new_type = _type_with_sections(
            _section_with_fields(REFERENCED_SECTION, []),
            _section_with_fields(OTHER_SECTION, []),
        )

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent_doc([])])}):
            blocker = referenced_section_field_removal_blocker(MagicMock(), old_type, new_type)

        assert REFERENCED_SECTION in blocker
        assert OTHER_SECTION in blocker


class TestGuardChecksBothHalves:
    """One guard, both halves of the rule."""

    def test_aborts_on_the_field_side_too(self) -> None:
        """An update that only empties a referenced section is refused by the same guard"""
        old_type = _type_with_sections(_section_with_fields(REFERENCED_SECTION, [FIELD_A]))
        new_type = _type_with_sections(_section_with_fields(REFERENCED_SECTION, []))

        with _patch_managers_by_type({ManagerType.TYPES: _types_manager([_dependent_doc([FIELD_A])])}):
            with pytest.raises(HTTPException) as exc_info:
                guard_referenced_section_removal(MagicMock(), old_type, new_type)

        assert exc_info.value.code == HTTP_BAD_REQUEST
