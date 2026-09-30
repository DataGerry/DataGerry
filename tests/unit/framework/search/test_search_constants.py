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
Unit tests for the values in cmdb.framework.search.search_constants that other code relies on

The search right has to name a right the rights tree knows - a typo does not raise, it turns both
search routes into a permanent 403 - and it has to be the right the object reads ask for. The reference
field kinds have to be real FieldType values, since a misspelt kind would silently stop counting that
kind of reference
"""
from cmdb.manager.rights_manager import RightsManager
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.framework.search.search_constants import (
    MAX_REFERENCED_MATCH_IDS,
    REFERENCE_FIELD_KINDS,
    SearchRight,
)
# -------------------------------------------------------------------------------------------------------------------- #

def test_every_search_right_exists_in_the_rights_tree() -> None:
    """user_has_right resolves the string against the tree; an unknown one never matches"""
    rights_manager = RightsManager()

    for member in SearchRight:
        assert rights_manager.get_right(member.value) is not None, member.value


def test_the_search_right_is_the_object_view_right() -> None:
    """A search reads objects, so it asks what every object read asks for"""
    assert SearchRight.VIEW.value == ObjectRightName.VIEW.value


def test_every_reference_kind_is_a_field_type() -> None:
    """A kind that is no FieldType value would never match a stored row"""
    assert set(REFERENCE_FIELD_KINDS) <= {field_type.value for field_type in FieldType}


def test_the_reference_kinds_are_exactly_the_three_that_point_at_an_object() -> None:
    """A plain reference, a reference section's field and a location - and no number or text kind"""
    assert set(REFERENCE_FIELD_KINDS) == {
        FieldType.REFERENCE.value, FieldType.REF_SECTION.value, FieldType.LOCATION.value,
    }


def test_the_id_list_cap_is_positive() -> None:
    """A cap of 0 would send every term to the slower database-side join"""
    assert MAX_REFERENCED_MATCH_IDS > 0
