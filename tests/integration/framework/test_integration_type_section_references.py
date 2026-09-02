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
Integration tests for the reference-section dependency lookup against a real MongoDB

`get_types_referencing_section` is the whole basis of the guard that refuses removing a section
another CmdbType pulls its fields from, and the one thing about it a mocked test cannot show is how
MongoDB matches a condition pair across an ARRAY. The lookup uses `$elemMatch` because two dotted
paths - `render_meta.sections.type` and `render_meta.sections.reference.type_id` - may be satisfied by
two DIFFERENT elements of the sections list: a type carrying an unrelated ref-section plus any section
naming the referenced type would match, and be refused for a dependency it does not have.

The decoy type seeded below is exactly that shape, so this suite fails if the query ever goes back to
dotted paths
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.manager.types_manager import TypesManager
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    get_section_reference_selections,
    get_types_referencing_section,
    referenced_section_field_removal_blocker,
    referenced_section_removal_blocker,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #
# Several tests below take the 'types' fixture purely for its side effect - it seeds the types the
# blocker reads through the patched ManagerProvider - and never touch the collection handle it yields
# pylint: disable=unused-argument
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper'

REFERENCED_TYPE_ID: int = 48101
DEPENDENT_TYPE_ID: int = 48102
DECOY_TYPE_ID: int = 48103
UNRELATED_TYPE_ID: int = 48104

ALL_TYPE_IDS: list[int] = [REFERENCED_TYPE_ID, DEPENDENT_TYPE_ID, DECOY_TYPE_ID, UNRELATED_TYPE_ID]

TEXT_FIELD: str = 'text_field'
SECOND_FIELD: str = 'second_field'
REFERENCED_SECTION: str = 'personal-data'
OTHER_SECTION: str = 'other'
REF_SECTION: str = 'personal-data-ref'


def _referenced_type_doc() -> dict[str, Any]:
    """The 'User' type of the bug report: one referenced section, one nothing references"""
    return make_type_doc(
        REFERENCED_TYPE_ID, 'integration-user',
        fields=[{'type': FieldType.TEXT, 'name': TEXT_FIELD, 'label': 'Text Field'}],
        sections=[
            {'type': SectionType.SECTION.value, 'name': REFERENCED_SECTION, 'label': 'Personal Data',
             'fields': [TEXT_FIELD]},
            {'type': SectionType.SECTION.value, 'name': OTHER_SECTION, 'label': 'Other', 'fields': []},
        ],
    )


def _dependent_type_doc() -> dict[str, Any]:
    """The 'test' type of the bug report: a ref-section pulling the referenced section"""
    return make_type_doc(
        DEPENDENT_TYPE_ID, 'integration-dependent',
        fields=[{'type': FieldType.REFERENCE, 'name': f'{REF_SECTION}-field', 'label': 'User',
                 'ref_types': [REFERENCED_TYPE_ID]}],
        sections=[{'type': SectionType.REF_SECTION.value, 'name': REF_SECTION, 'label': 'Personal Data',
                   'reference': {'type_id': REFERENCED_TYPE_ID, 'section_name': REFERENCED_SECTION,
                                 'selected_fields': [TEXT_FIELD]},
                   'fields': []}],
    )


def _decoy_type_doc() -> dict[str, Any]:
    """
    The false positive a dotted-path query would produce

    Its ref-section points at an entirely different type, and a SEPARATE plain section happens to
    carry a 'reference.type_id' naming the referenced type. No element satisfies both conditions, so
    this type is NOT a dependent - but two dotted paths would match it.
    """
    return make_type_doc(
        DECOY_TYPE_ID, 'integration-decoy',
        fields=[],
        sections=[
            {'type': SectionType.REF_SECTION.value, 'name': 'elsewhere', 'label': 'Elsewhere',
             'reference': {'type_id': UNRELATED_TYPE_ID, 'section_name': 'whatever',
                           'selected_fields': []},
             'fields': []},
            {'type': SectionType.SECTION.value, 'name': 'decoy', 'label': 'Decoy',
             'reference': {'type_id': REFERENCED_TYPE_ID, 'section_name': REFERENCED_SECTION},
             'fields': []},
        ],
    )


def _self_referencing_type_doc() -> dict[str, Any]:
    """A type whose own ref-section points at one of its own sections"""
    return make_type_doc(
        UNRELATED_TYPE_ID, 'integration-self-ref',
        fields=[{'type': FieldType.TEXT, 'name': TEXT_FIELD, 'label': 'Text Field'}],
        sections=[
            {'type': SectionType.SECTION.value, 'name': REFERENCED_SECTION, 'label': 'Own',
             'fields': [TEXT_FIELD]},
            {'type': SectionType.REF_SECTION.value, 'name': 'self-ref', 'label': 'Self',
             'reference': {'type_id': UNRELATED_TYPE_ID, 'section_name': REFERENCED_SECTION,
                           'selected_fields': []},
             'fields': []},
        ],
    )


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the four types and patches the helper's ManagerProvider onto a real TypesManager"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})

    for doc in (_referenced_type_doc(), _dependent_type_doc(), _decoy_type_doc(),
                _self_referencing_type_doc()):
        collection.insert_one({**doc, 'creation_time': datetime.now(timezone.utc)})

    types_manager = TypesManager(database_manager, database_name)

    with patch(f'{HELPER_PATH}.ManagerProvider.get_manager',
               side_effect=lambda manager_type, _user:
                   types_manager if manager_type == ManagerType.TYPES else MagicMock()):
        yield collection

    collection.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


def _without_section(doc: dict[str, Any], section_name: str) -> CmdbType:
    """The type as an update that drops one section would persist it"""
    stripped = {**doc, 'render_meta': {**doc['render_meta']}}
    stripped['render_meta']['sections'] = [
        section for section in doc['render_meta']['sections'] if section['name'] != section_name
    ]

    return CmdbType.from_data(stripped)

# -------------------------------------------------------------------------------------------------------------------- #

def test_finds_the_real_dependent(types) -> None:
    """The dependent type is found for the section it actually references"""
    found = get_types_referencing_section(MagicMock(), REFERENCED_TYPE_ID, REFERENCED_SECTION)

    assert [dependent['public_id'] for dependent in found] == [DEPENDENT_TYPE_ID]


def test_does_not_match_the_decoy(types) -> None:
    """
    The reason the lookup uses $elemMatch

    The decoy has a ref-section AND a section naming the referenced type, but in two different
    array elements. Two dotted paths would match it and refuse a dependency that does not exist.
    """
    found = get_types_referencing_section(MagicMock(), REFERENCED_TYPE_ID, REFERENCED_SECTION)

    assert DECOY_TYPE_ID not in [dependent['public_id'] for dependent in found]


def test_finds_nothing_for_an_unreferenced_section(types) -> None:
    """The referenced type's other section is free to remove"""
    assert get_types_referencing_section(MagicMock(), REFERENCED_TYPE_ID, OTHER_SECTION) == []


def test_without_a_section_name_matches_any_reference_to_the_type(types) -> None:
    """The type-deletion check: is this type referenced at all"""
    found = get_types_referencing_section(MagicMock(), REFERENCED_TYPE_ID)

    assert [dependent['public_id'] for dependent in found] == [DEPENDENT_TYPE_ID]


def test_the_exclusion_leaves_out_the_given_type(types) -> None:
    """A self-referencing type must not block its own update or deletion"""
    with_self = get_types_referencing_section(MagicMock(), UNRELATED_TYPE_ID, REFERENCED_SECTION)
    without_self = get_types_referencing_section(
        MagicMock(), UNRELATED_TYPE_ID, REFERENCED_SECTION, exclude_type_id=UNRELATED_TYPE_ID,
    )

    assert [dependent['public_id'] for dependent in with_self] == [UNRELATED_TYPE_ID]
    assert without_self == []


def test_the_result_carries_no_object_id(types) -> None:
    """These dicts go into a REST response, where an ObjectId is not serialisable"""
    found = get_types_referencing_section(MagicMock(), REFERENCED_TYPE_ID, REFERENCED_SECTION)

    assert set(found[0]) == {'public_id', 'name', 'label'}


def test_the_blocker_refuses_removing_the_referenced_section(types) -> None:
    """End to end against stored types: the reported edit is refused"""
    old_type = CmdbType.from_data(_referenced_type_doc())
    new_type = _without_section(_referenced_type_doc(), REFERENCED_SECTION)

    blocker = referenced_section_removal_blocker(MagicMock(), old_type, new_type)

    assert blocker is not None
    assert REFERENCED_SECTION in blocker
    assert str(DEPENDENT_TYPE_ID) in blocker


def test_the_blocker_allows_removing_the_unreferenced_section(types) -> None:
    """Ordinary edits are not affected by the guard"""
    old_type = CmdbType.from_data(_referenced_type_doc())
    new_type = _without_section(_referenced_type_doc(), OTHER_SECTION)

    assert referenced_section_removal_blocker(MagicMock(), old_type, new_type) is None


def test_the_blocker_refuses_a_self_reference_that_survives(types) -> None:
    """A type's own ref-section counts, and is read from the payload rather than the database"""
    old_type = CmdbType.from_data(_self_referencing_type_doc())
    new_type = _without_section(_self_referencing_type_doc(), REFERENCED_SECTION)

    blocker = referenced_section_removal_blocker(MagicMock(), old_type, new_type)

    assert blocker is not None
    assert str(UNRELATED_TYPE_ID) in blocker


def test_the_blocker_allows_dropping_a_section_and_its_own_reference_together(types) -> None:
    """One update removing both sides leaves nothing dangling, so it must be allowed"""
    doc = _self_referencing_type_doc()
    old_type = CmdbType.from_data(doc)
    stripped = {**doc, 'render_meta': {**doc['render_meta'], 'sections': []}}

    assert referenced_section_removal_blocker(MagicMock(), old_type, CmdbType.from_data(stripped)) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                               the field side: refuse only what would show nothing                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def _referenced_type_with_fields(section_field_names: list[str]) -> CmdbType:
    """The referenced type as an update carrying the given field names in the referenced section"""
    doc = make_type_doc(
        REFERENCED_TYPE_ID, 'integration-user',
        fields=[{'type': FieldType.TEXT, 'name': name, 'label': name} for name in section_field_names],
        sections=[
            {'type': SectionType.SECTION.value, 'name': REFERENCED_SECTION, 'label': 'Personal Data',
             'fields': list(section_field_names)},
            {'type': SectionType.SECTION.value, 'name': OTHER_SECTION, 'label': 'Other', 'fields': []},
        ],
    )

    return CmdbType.from_data(doc)


def test_the_selections_of_a_section_are_read_back(types) -> None:
    """The field check needs the dependents' selections, not just their identity"""
    selections = get_section_reference_selections(
        MagicMock(), REFERENCED_TYPE_ID, REFERENCED_SECTION, exclude_type_id=REFERENCED_TYPE_ID,
    )

    assert len(selections) == 1
    assert selections[0]['public_id'] == DEPENDENT_TYPE_ID
    assert selections[0]['selected_fields'] == [TEXT_FIELD]


def test_the_selection_lookup_ignores_the_decoy(types) -> None:
    """Same $elemMatch reasoning as the identity lookup, on the projection that reads sections too"""
    selections = get_section_reference_selections(
        MagicMock(), REFERENCED_TYPE_ID, REFERENCED_SECTION, exclude_type_id=REFERENCED_TYPE_ID,
    )

    assert DECOY_TYPE_ID not in [selection['public_id'] for selection in selections]


@pytest.mark.parametrize('before, after, refused', [
    # The stored dependent selects TEXT_FIELD and nothing else, so what matters is whether
    # TEXT_FIELD is still in the section afterwards - not how many fields the section has left
    ([TEXT_FIELD], [], True),
    ([TEXT_FIELD, SECOND_FIELD], [SECOND_FIELD], True),
    ([TEXT_FIELD, SECOND_FIELD], [TEXT_FIELD], False),
    ([TEXT_FIELD, SECOND_FIELD], [], True),
    ([TEXT_FIELD], [TEXT_FIELD], False),
    ([TEXT_FIELD], [TEXT_FIELD, SECOND_FIELD], False),
], ids=['selected-field-removed', 'selected-removed-other-kept', 'unselected-field-removed',
        'all-removed', 'unchanged', 'field-added'])
def test_the_field_blocker_refuses_exactly_the_emptying_edits(
        types, before: list[str], after: list[str], refused: bool) -> None:
    """
    Against a stored dependent that selects TEXT_FIELD only

    Every row here is a measured render outcome: the refused ones are the configurations that render
    an EMPTY block, the allowed ones still render something.
    """
    blocker = referenced_section_field_removal_blocker(
        MagicMock(), _referenced_type_with_fields(before), _referenced_type_with_fields(after),
    )

    assert (blocker is not None) is refused


def test_the_field_blocker_names_the_dependent(types) -> None:
    """The refusal has to say which Type it is protecting"""
    blocker = referenced_section_field_removal_blocker(
        MagicMock(), _referenced_type_with_fields([TEXT_FIELD]), _referenced_type_with_fields([]),
    )

    assert 'would show nothing' in blocker
    assert str(DEPENDENT_TYPE_ID) in blocker


def test_a_section_that_already_showed_nothing_is_not_protected(types) -> None:
    """An already-broken configuration must not block unrelated edits"""
    blocker = referenced_section_field_removal_blocker(
        MagicMock(), _referenced_type_with_fields([SECOND_FIELD]), _referenced_type_with_fields([]),
    )

    assert blocker is None
