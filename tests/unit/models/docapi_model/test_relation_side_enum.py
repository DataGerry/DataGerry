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
Unit tests for cmdb.models.docapi_model.relation_side_enum.RelationSide

Pins the wire values and confirms the enum compares equal to the bare strings templates pass in.
"""
from cmdb.models.docapi_model.relation_side_enum import RelationSide
# -------------------------------------------------------------------------------------------------------------------- #


class TestRelationSide:
    """RelationSide is a string enum with the traversal-direction values."""

    def test_values(self) -> None:
        """The enum members carry their expected wire values."""
        assert RelationSide.PARENT == 'parent'
        assert RelationSide.CHILD == 'child'

    def test_membership(self) -> None:
        """Exactly the two traversal directions exist."""
        assert {member.value for member in RelationSide} == {'parent', 'child'}
