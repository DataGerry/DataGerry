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
Unit tests for cmdb.models.special_type_model.schemas.schema_provider

Pins the SpecialType -> blueprint dispatch: each valid SpecialType returns the matching schema
(identified by its special_type marker), and an invalid value raises ValueError before any
dispatch.
"""
import pytest

from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize('special_type', [SpecialType.SUPERNET, SpecialType.SUBNET, SpecialType.VLAN])
def test_get_schema_returns_blueprint_marked_with_requested_special_type(special_type: SpecialType) -> None:
    """Each SpecialType resolves to a blueprint carrying that same special_type marker"""
    schema = SchemaProvider().get_schema(special_type)

    assert schema[TypeSchemaKey.SPECIAL_TYPE] == special_type


def test_get_schema_raises_value_error_for_invalid_special_type() -> None:
    """A value that is not a valid SpecialType raises ValueError instead of dispatching"""
    with pytest.raises(ValueError):
        SchemaProvider().get_schema('NOT_A_SPECIAL_TYPE')  # type: ignore[arg-type]
