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

Pins the SpecialType -> blueprint dispatch: every SpecialType member returns the matching schema
(identified by its special_type marker), and an invalid value raises ValueError before any
dispatch. The dispatch is parametrized over the enum itself, so a new member without a branch in
SchemaProvider fails here rather than at runtime.

Also pins that the provider stays a PURE function. CABLE is the only member whose blueprint depends on
a value from the database, and it takes that value as an argument - so no branch here may ever reach
for a manager, and every member must still answer with no argument at all
"""
import pytest

from cmdb.models.type_model import FieldKey, TypeSchemaKey
from cmdb.models.special_type_model.cable_constants import CableField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize('special_type', list(SpecialType), ids=str)
def test_get_schema_returns_blueprint_marked_with_requested_special_type(special_type: SpecialType) -> None:
    """Each SpecialType resolves to a blueprint carrying that same special_type marker"""
    schema = SchemaProvider().get_schema(special_type)

    assert schema[TypeSchemaKey.SPECIAL_TYPE] == special_type


def test_get_schema_raises_value_error_for_invalid_special_type() -> None:
    """A value that is not a valid SpecialType raises ValueError instead of dispatching"""
    with pytest.raises(ValueError):
        SchemaProvider().get_schema('NOT_A_SPECIAL_TYPE')  # type: ignore[arg-type]


def test_get_schema_passes_the_cable_type_values_to_the_cable_blueprint() -> None:
    """The one member whose blueprint depends on a value the caller reads from the database"""
    schema = SchemaProvider().get_schema(SpecialType.CABLE, ['Cat6a', 'OM4'])

    cable_type = next(
        field for field in schema[TypeSchemaKey.FIELDS] if field[FieldKey.NAME] == CableField.TYPE
    )

    assert [option[FieldKey.NAME] for option in cable_type[FieldKey.OPTIONS]] == ['Cat6a', 'OM4']


def test_the_cable_blueprint_answers_without_any_values() -> None:
    """
    Every member has to stay callable with the special_type alone

    The parametrized dispatch above passes none, and so does any caller that only needs the shape -
    an omitted list is an empty select, not a crash.
    """
    schema = SchemaProvider().get_schema(SpecialType.CABLE)

    cable_type = next(
        field for field in schema[TypeSchemaKey.FIELDS] if field[FieldKey.NAME] == CableField.TYPE
    )

    assert cable_type[FieldKey.OPTIONS] == []


@pytest.mark.parametrize(
    'special_type',
    [member for member in SpecialType if member is not SpecialType.CABLE],
    ids=str,
)
def test_cable_type_values_are_ignored_by_every_other_member(special_type: SpecialType) -> None:
    """
    Passing the values must not change a blueprint that has nothing to do with cables

    Guards against the argument leaking into a shared code path later - the route sends it only for
    CABLE today, but nothing stops a caller from always passing it.
    """
    assert SchemaProvider().get_schema(special_type, ['Cat6a']) == SchemaProvider().get_schema(special_type)
