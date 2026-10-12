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
Unit tests for PersonReferenceType - the enum every polymorphic ISMS person reference is stored beside

Pure tests: no Mongo, no Flask. Its values are the same tokens as the PERSON / PERSON_GROUP SpecialTypes, so
an ISMS '_ref_type' and the 'ref_type' of a person field speak one vocabulary
"""
from cmdb.models.person_group_model import PersonReferenceType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_constants import PersonRefKind
# -------------------------------------------------------------------------------------------------------------------- #

class TestPersonReferenceType:
    """The enum that says which kind a polymorphic ISMS reference holds."""

    def test_holds_exactly_the_two_referenceable_kinds(self) -> None:
        """Every polymorphic ISMS field is stored beside a '_ref_type' carrying one of these"""
        assert {member.value for member in PersonReferenceType} == {'PERSON', 'PERSON_GROUP'}

    def test_members_compare_equal_to_their_stored_string(self) -> None:
        """The cleanup and the reports filter with the member's value, and read plain strings."""
        assert PersonReferenceType.PERSON == 'PERSON'
        assert PersonReferenceType.PERSON_GROUP.value == 'PERSON_GROUP'

    def test_speaks_the_vocabulary_of_the_person_special_types(self) -> None:
        """resolve_person_kinds answers SpecialType tokens; the ISMS check compares them to these values"""
        assert {member.value for member in PersonReferenceType} == {
            member.value for member in SpecialType.get_person_types()
        }

    def test_every_reference_type_is_a_person_ref_kind(self) -> None:
        """A person field restricted to one kind uses the same token as the ISMS reference"""
        assert {member.value for member in PersonReferenceType} <= {member.value for member in PersonRefKind}
