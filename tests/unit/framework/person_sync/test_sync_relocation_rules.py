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
Unit tests for cmdb.framework.person_sync.sync_relocation_rules and sync_documents.relocated_person

Pinned per blocker: a value the new Type does not declare - or declares with another kind - blocks, an empty one does
not; rows of an undeclared multi-data section block; a reference field blocks unless its ref_types name the new Type,
a reference section field always; a relation side blocks unless its definition allows the new Type there; a location
node blocks. The moved document keeps what the new Type declares, fills its defaults and drops the fingerprint
"""
from typing import Any

import pytest

from cmdb.models.special_type_model.person_type_constants import PersonField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import RelocationBlocker
from cmdb.framework.person_sync.sync_documents import relocated_person
from cmdb.framework.person_sync.sync_relocation_rules import (
    PersonRelocation,
    location_blockers,
    lost_value_blockers,
    reference_blockers,
    relation_blockers,
)
# -------------------------------------------------------------------------------------------------------------------- #

OLD_TYPE_ID: int = 61
NEW_TYPE_ID: int = 62
HOLDER_TYPE_ID: int = 63
PERSON_ID: int = 71
OTHER_PERSON_ID: int = 72
HOLDER_ID: int = 81
RELATION_ID: int = 91
DEFINITION_ID: int = 92
OWN_FIELD: str = 'badge'
DEFAULTED_FIELD: str = 'site'
DEFAULT: str = 'HQ'
SECTION: str = 'history'
ROW_FIELD: str = 'previous'


def _new_type(extra_fields: list[dict[str, Any]] | None = None,
              sections: list[dict[str, Any]] | None = None) -> CmdbType:
    """The new PERSON Type, with extra fields and sections"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, 'new', NEW_TYPE_ID)
    document['fields'].extend(extra_fields or [])
    document['render_meta']['sections'].extend(sections or [])

    return CmdbType.from_data(document)


def _person(fields: list[dict[str, Any]], sections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A stored person in the old Type"""
    return {'public_id': PERSON_ID, 'type_id': OLD_TYPE_ID, 'fields': fields, 'multi_data_sections': sections or [],
            'sync_hash': 'h', 'system_ref': {'kind': 'user', 'id': 5}, 'active': True}


def _rows(value: Any) -> list[dict[str, Any]]:
    """One multi-data section with one row holding the value"""
    return [{'section_id': SECTION, 'highest_id': 1, 'values': [
        {'multi_data_id': 1, 'data': [{'name': ROW_FIELD, 'value': value, 'type': 'text'}]}]}]


ROW_SECTION: dict[str, Any] = {'type': 'multi-data-section', 'name': SECTION, 'label': 'History', 'fields': [ROW_FIELD]}
ROW_DEFINITION: dict[str, Any] = {'type': 'text', 'name': ROW_FIELD, 'label': 'Previous'}


class TestPersonRelocation:
    """The answered shape."""

    def test_blocked_and_json(self) -> None:
        """Blocked with any blocker"""
        relocation = PersonRelocation(5, PERSON_ID, OLD_TYPE_ID, NEW_TYPE_ID, ('x',))

        assert relocation.blocked is True
        assert PersonRelocation(5, PERSON_ID, OLD_TYPE_ID, NEW_TYPE_ID).blocked is False
        assert relocation.to_json() == {'user_id': 5, 'person_id': PERSON_ID, 'from_type_id': OLD_TYPE_ID,
                                        'to_type_id': NEW_TYPE_ID, 'blockers': ['x']}


class TestLostValueBlockers:
    """What the new Type cannot keep."""

    def test_the_base_fields_and_empty_extras_pass(self) -> None:
        """Synced values live in every PERSON Type; an empty own value loses nothing"""
        person = _person([{'name': PersonField.DISPLAY_NAME.value, 'value': 'Ann', 'type': 'text'},
                          {'name': OWN_FIELD, 'value': '', 'type': 'text'}])

        assert lost_value_blockers(person, _new_type()) == []

    def test_an_undeclared_value_blocks(self) -> None:
        """Named"""
        person = _person([{'name': OWN_FIELD, 'value': 'B-7', 'type': 'text'}])

        assert lost_value_blockers(person, _new_type()) == [
            RelocationBlocker.LOST_FIELDS.value.format(names=[OWN_FIELD], type_id=NEW_TYPE_ID)]

    def test_another_kind_blocks(self) -> None:
        """Declared as a number in the new Type"""
        person = _person([{'name': OWN_FIELD, 'value': 'B-7', 'type': 'text'}])
        new_type = _new_type([{'type': 'number', 'name': OWN_FIELD, 'label': 'Badge'}])

        assert lost_value_blockers(person, new_type) == [
            RelocationBlocker.LOST_FIELDS.value.format(names=[OWN_FIELD], type_id=NEW_TYPE_ID)]

    def test_rows_of_an_undeclared_section_block(self) -> None:
        """Named by section"""
        assert lost_value_blockers(_person([], _rows('x')), _new_type()) == [
            RelocationBlocker.LOST_SECTIONS.value.format(names=[SECTION], type_id=NEW_TYPE_ID)]

    def test_empty_rows_and_declared_sections_pass(self) -> None:
        """Nothing to lose"""
        declared = _new_type([ROW_DEFINITION], [ROW_SECTION])

        assert lost_value_blockers(_person([], _rows(None)), _new_type()) == []
        assert lost_value_blockers(_person([], _rows('x')), declared) == []


class TestReferenceBlockers:
    """Other objects referencing the person."""

    def _holder(self, name: str, kind: str, value: int = PERSON_ID) -> dict[str, Any]:
        """A holder with one reference entry"""
        return {'public_id': HOLDER_ID, 'type_id': HOLDER_TYPE_ID, 'fields': [{'name': name, 'value': value,
                                                                               'type': kind}]}

    def _types(self, ref_types: Any) -> dict[int, CmdbType]:
        """The holder's Type with a ref field"""
        document = build_default_person_type(SpecialType.PERSON, 'holder', HOLDER_TYPE_ID)
        document['fields'].append({'type': 'ref', 'name': 'owner', 'label': 'Owner', 'ref_types': ref_types})

        return {HOLDER_TYPE_ID: CmdbType.from_data(document)}

    @pytest.mark.parametrize('ref_types', [[NEW_TYPE_ID], [OLD_TYPE_ID, NEW_TYPE_ID], NEW_TYPE_ID])
    def test_a_field_allowing_the_new_type_passes(self, ref_types: Any) -> None:
        """A list or a single id"""
        assert reference_blockers(PERSON_ID, NEW_TYPE_ID, [self._holder('owner', 'ref')], self._types(ref_types)) == []

    def test_a_field_naming_only_the_old_type_blocks(self) -> None:
        """Named with what it allows"""
        assert reference_blockers(PERSON_ID, NEW_TYPE_ID, [self._holder('owner', 'ref')],
                                  self._types([OLD_TYPE_ID])) == [
            RelocationBlocker.REFERENCE_FIELD.value.format(holder_id=HOLDER_ID, name='owner', type_ids=[OLD_TYPE_ID])]

    def test_a_section_field_always_blocks(self) -> None:
        """It shows the old Type's fields"""
        holder = self._holder('owner-field', 'ref-section-field')

        assert reference_blockers(PERSON_ID, NEW_TYPE_ID, [holder], self._types([NEW_TYPE_ID])) == [
            RelocationBlocker.REFERENCE_SECTION.value.format(holder_id=HOLDER_ID, name='owner-field')]

    def test_another_persons_reference_and_other_kinds_are_ignored(self) -> None:
        """Only the person's, only references"""
        holders = [self._holder('owner', 'ref', OTHER_PERSON_ID), self._holder('owner', 'person')]

        assert reference_blockers(PERSON_ID, NEW_TYPE_ID, holders, self._types([OLD_TYPE_ID])) == []

    def test_a_reference_row_counts(self) -> None:
        """Multi-data rows are searched too"""
        holder = {'public_id': HOLDER_ID, 'type_id': HOLDER_TYPE_ID, 'fields': [], 'multi_data_sections': [
            {'section_id': 's', 'values': [{'data': [{'name': 'owner', 'value': PERSON_ID, 'type': 'ref'}]}]}]}

        assert len(reference_blockers(PERSON_ID, NEW_TYPE_ID, [holder], self._types([OLD_TYPE_ID]))) == 1


class TestRelationAndLocationBlockers:
    """Relation sides, the location tree."""

    @pytest.mark.parametrize('side_key, allowed_key, side', [
        ('relation_parent_id', 'parent_type_ids', 'parent'),
        ('relation_child_id', 'child_type_ids', 'child'),
    ])
    def test_a_side_not_allowing_the_new_type_blocks(self, side_key: str, allowed_key: str, side: str) -> None:
        """Named by relation, definition and side; allowed passes"""
        relation = {'public_id': RELATION_ID, 'relation_id': DEFINITION_ID, side_key: PERSON_ID}
        strict = {DEFINITION_ID: {allowed_key: [OLD_TYPE_ID]}}
        open_ = {DEFINITION_ID: {allowed_key: [OLD_TYPE_ID, NEW_TYPE_ID]}}

        assert relation_blockers(PERSON_ID, NEW_TYPE_ID, [relation], strict) == [
            RelocationBlocker.RELATION_SIDE.value.format(relation_id=RELATION_ID, definition_id=DEFINITION_ID,
                                                         type_ids=[OLD_TYPE_ID], side=side)]
        assert relation_blockers(PERSON_ID, NEW_TYPE_ID, [relation], open_) == []

    def test_another_objects_side_is_ignored(self) -> None:
        """The person is the child; the parent side is not its"""
        relation = {'public_id': RELATION_ID, 'relation_id': DEFINITION_ID, 'relation_parent_id': OTHER_PERSON_ID,
                    'relation_child_id': PERSON_ID}
        definitions = {DEFINITION_ID: {'parent_type_ids': [OLD_TYPE_ID], 'child_type_ids': [NEW_TYPE_ID]}}

        assert relation_blockers(PERSON_ID, NEW_TYPE_ID, [relation], definitions) == []

    def test_a_placed_person_blocks(self) -> None:
        """Only the placed one"""
        assert location_blockers(PERSON_ID, {PERSON_ID}) == [RelocationBlocker.LOCATION.value]
        assert location_blockers(PERSON_ID, {OTHER_PERSON_ID}) == []


class TestRelocatedPerson:
    """The person as it lives in the new Type."""

    def test_kept_dropped_filled(self) -> None:
        """The new Type, its fields kept, an undeclared one dropped, a default filled, no fingerprint, link kept"""
        stored = _person([{'name': PersonField.DISPLAY_NAME.value, 'value': 'Ann', 'type': 'text'},
                          {'name': OWN_FIELD, 'value': '', 'type': 'text'}], _rows('x'))
        new_type = _new_type([{'type': 'text', 'name': DEFAULTED_FIELD, 'label': 'Site', 'value': DEFAULT},
                              ROW_DEFINITION], [ROW_SECTION])

        after = relocated_person(stored, new_type)

        values = {entry['name']: entry['value'] for entry in after['fields']}
        assert after['type_id'] == NEW_TYPE_ID
        assert values[PersonField.DISPLAY_NAME.value] == 'Ann'
        assert values[DEFAULTED_FIELD] == DEFAULT
        assert OWN_FIELD not in values
        assert after['multi_data_sections'][0]['values'][0]['data'][0]['value'] == 'x'
        assert 'sync_hash' not in after
        assert after['system_ref'] == stored['system_ref']
        assert stored['type_id'] == OLD_TYPE_ID

    def test_an_undeclared_section_goes(self) -> None:
        """Its rows were empty or the move was refused"""
        assert relocated_person(_person([], _rows(None)), _new_type())['multi_data_sections'] == []
