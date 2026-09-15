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
Unit tests for CmdbRelation

Covers the (de)serialization contract - the round trip through ``from_data`` / ``to_json``, the
optional keys a stored document may legitimately lack, and the typed errors raised for input that
cannot be turned into a relation - plus ``remove_type_id_from_relation``, the in-memory cascade the
type deletion uses. Pure tests: no Mongo, no Flask.
"""
from typing import Any

import pytest

from cmdb.models.relation_model import CmdbRelation, RelationKey
from cmdb.errors.models.cmdb_relation import (
    CmdbRelationInitError,
    CmdbRelationInitFromDataError,
    CmdbRelationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_PUBLIC_ID: int = 12
PARENT_TYPE_ID: int = 1
CHILD_TYPE_ID: int = 2
OTHER_TYPE_ID: int = 3

SECTION: dict[str, Any] = {'type': 'section', 'name': 's1', 'label': 'Section 1', 'fields': ['f1']}


def _relation_data(**overrides: Any) -> dict[str, Any]:
    """Builds a complete stored CmdbRelation document, with the given keys overridden."""
    data: dict[str, Any] = {
        RelationKey.PUBLIC_ID.value: RELATION_PUBLIC_ID,
        RelationKey.RELATION_NAME.value: 'runs-on',
        RelationKey.PARENT_TYPE_IDS.value: [PARENT_TYPE_ID],
        RelationKey.CHILD_TYPE_IDS.value: [CHILD_TYPE_ID],
        RelationKey.RELATION_NAME_PARENT.value: 'is-parent-of',
        RelationKey.RELATION_NAME_CHILD.value: 'is-child-of',
        RelationKey.DESCRIPTION.value: 'a description',
        RelationKey.RELATION_ICON_PARENT.value: 'fa-parent',
        RelationKey.RELATION_COLOR_PARENT.value: '#ffffff',
        RelationKey.RELATION_ICON_CHILD.value: 'fa-child',
        RelationKey.RELATION_COLOR_CHILD.value: '#000000',
        RelationKey.SECTIONS.value: [SECTION],
        RelationKey.FIELDS.value: [{'type': 'text', 'name': 'f1', 'label': 'Field 1'}],
    }
    data.update(overrides)

    return data


class TestFromData:
    """from_data reads a stored CmdbRelation document."""

    def test_reads_every_documented_key(self) -> None:
        """Each document key ends up on the instance."""
        relation = CmdbRelation.from_data(_relation_data())

        assert relation.get_public_id() == RELATION_PUBLIC_ID
        assert relation.relation_name == 'runs-on'
        assert relation.parent_type_ids == [PARENT_TYPE_ID]
        assert relation.child_type_ids == [CHILD_TYPE_ID]
        assert relation.relation_name_parent == 'is-parent-of'
        assert relation.relation_name_child == 'is-child-of'
        assert relation.description == 'a description'
        assert relation.relation_icon_parent == 'fa-parent'
        assert relation.relation_color_parent == '#ffffff'
        assert relation.relation_icon_child == 'fa-child'
        assert relation.relation_color_child == '#000000'

    def test_builds_the_sections_as_models(self) -> None:
        """A section dict becomes a TypeFieldSection carrying its field identifiers."""
        relation = CmdbRelation.from_data(_relation_data())

        assert len(relation.sections) == 1
        assert relation.sections[0].name == 's1'
        assert relation.sections[0].fields == ['f1']

    @pytest.mark.parametrize('missing_key', [RelationKey.SECTIONS.value, RelationKey.FIELDS.value])
    def test_optional_list_keys_default_to_empty(self, missing_key: str) -> None:
        """A document without 'sections' / 'fields' still reads, with the list defaulted to empty."""
        data = _relation_data()
        data.pop(missing_key)

        relation = CmdbRelation.from_data(data)

        assert getattr(relation, missing_key) == []

    @pytest.mark.parametrize('null_key', [RelationKey.SECTIONS.value, RelationKey.FIELDS.value])
    def test_explicit_null_list_keys_are_read_as_empty(self, null_key: str) -> None:
        """An explicit null (what an older payload could store) is read as empty, not as None."""
        relation = CmdbRelation.from_data(_relation_data(**{null_key: None}))

        assert getattr(relation, null_key) == []

    def test_optional_presentation_keys_default_to_none(self) -> None:
        """The icon / color / description keys are optional and default to None."""
        data = _relation_data()
        for optional_key in (
            RelationKey.DESCRIPTION.value,
            RelationKey.RELATION_ICON_PARENT.value,
            RelationKey.RELATION_COLOR_PARENT.value,
            RelationKey.RELATION_ICON_CHILD.value,
            RelationKey.RELATION_COLOR_CHILD.value,
        ):
            data.pop(optional_key)

        relation = CmdbRelation.from_data(data)

        assert relation.description is None
        assert relation.relation_icon_parent is None
        assert relation.relation_color_parent is None
        assert relation.relation_icon_child is None
        assert relation.relation_color_child is None

    def test_wraps_a_malformed_section(self) -> None:
        """A section that is not a dict cannot be built and is reported as a typed error."""
        with pytest.raises(CmdbRelationInitFromDataError):
            CmdbRelation.from_data(_relation_data(sections=['not-a-section']))

    def test_wraps_a_missing_public_id(self) -> None:
        """A document without a public_id cannot be turned into a relation."""
        data = _relation_data()
        data.pop(RelationKey.PUBLIC_ID.value)

        with pytest.raises(CmdbRelationInitFromDataError):
            CmdbRelation.from_data(data)


class TestInit:
    """The constructor reports unusable input as a typed error."""

    def test_wraps_a_non_numeric_public_id(self) -> None:
        """CmdbDAO casts the public_id, so a non-numeric one fails the initialisation."""
        with pytest.raises(CmdbRelationInitError):
            CmdbRelation(
                public_id='not-an-int',
                relation_name='r',
                parent_type_ids=[PARENT_TYPE_ID],
                child_type_ids=[CHILD_TYPE_ID],
                relation_name_parent='is-parent-of',
                relation_name_child='is-child-of',
            )


class TestToJson:
    """to_json serialises a CmdbRelation back into a document."""

    def test_round_trips_a_document(self) -> None:
        """A document survives from_data -> to_json unchanged."""
        data = _relation_data()

        assert CmdbRelation.to_json(CmdbRelation.from_data(data)) == data

    def test_serialises_a_relation_without_sections(self) -> None:
        """An unset 'sections' serialises as an empty list instead of raising."""
        relation = CmdbRelation(
            public_id=RELATION_PUBLIC_ID,
            relation_name='r',
            parent_type_ids=[PARENT_TYPE_ID],
            child_type_ids=[CHILD_TYPE_ID],
            relation_name_parent='is-parent-of',
            relation_name_child='is-child-of',
        )

        assert CmdbRelation.to_json(relation)[RelationKey.SECTIONS.value] == []

    def test_wraps_a_relation_without_a_public_id(self) -> None:
        """public_id 0 means 'not assigned yet', which cannot be serialised."""
        relation = CmdbRelation.from_data(_relation_data(public_id=0))

        with pytest.raises(CmdbRelationToJsonError):
            CmdbRelation.to_json(relation)


class TestRemoveTypeIdFromRelation:
    """remove_type_id_from_relation drops a deleted CmdbType from both id lists."""

    def test_removes_the_id_from_both_lists(self) -> None:
        """A type used as parent AND child is removed from both."""
        relation = CmdbRelation.from_data(
            _relation_data(parent_type_ids=[PARENT_TYPE_ID, OTHER_TYPE_ID],
                           child_type_ids=[CHILD_TYPE_ID, OTHER_TYPE_ID])
        )

        relation.remove_type_id_from_relation(OTHER_TYPE_ID)

        assert relation.parent_type_ids == [PARENT_TYPE_ID]
        assert relation.child_type_ids == [CHILD_TYPE_ID]

    def test_keeps_the_other_side_untouched(self) -> None:
        """A type used only as child is removed there and nowhere else."""
        relation = CmdbRelation.from_data(_relation_data())

        relation.remove_type_id_from_relation(CHILD_TYPE_ID)

        assert relation.parent_type_ids == [PARENT_TYPE_ID]
        assert relation.child_type_ids == []

    def test_unknown_id_changes_nothing(self) -> None:
        """Removing a type the relation never allowed is a no-op."""
        relation = CmdbRelation.from_data(_relation_data())

        relation.remove_type_id_from_relation(OTHER_TYPE_ID)

        assert relation.parent_type_ids == [PARENT_TYPE_ID]
        assert relation.child_type_ids == [CHILD_TYPE_ID]

    def test_unset_id_lists_are_treated_as_empty(self) -> None:
        """A relation whose type lists were never set has nothing to remove and must not raise."""
        relation = CmdbRelation(
            public_id=RELATION_PUBLIC_ID,
            relation_name='r',
            parent_type_ids=None,
            child_type_ids=None,
            relation_name_parent='is-parent-of',
            relation_name_child='is-child-of',
        )

        relation.remove_type_id_from_relation(OTHER_TYPE_ID)

        assert relation.parent_type_ids is None
        assert relation.child_type_ids is None
