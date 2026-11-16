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
Unit tests for cmdb.framework.person_types.default_person_types

The free-name rule, the plan of what is missing, the stored document of a default Type (checked against the type
structure rules and the model) and the seeding against a mocked manager: nothing when both defaults exist, the
missing ones under reserved ids, recorded on a ledger before the insert
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.type_model import CmdbType, FieldKey, TypeSchemaKey
from cmdb.security.acl.acl_constants import AclKey
from cmdb.models.type_model.type_structure_rules import validate_type_structure
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import (
    DefaultPersonType,
    PersonField,
    PersonGroupField,
)
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.default_person_types import (
    build_default_person_type,
    free_type_name,
    markers_with_default,
    plan_default_person_types,
    seed_default_person_types,
)
from cmdb.framework.person_types.person_types_constants import SEED_PROJECTION, SYSTEM_AUTHOR_ID
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_NAME: str = DefaultPersonType.PERSON_NAME.value
GROUP_NAME: str = DefaultPersonType.PERSON_GROUP_NAME.value
RESERVED_IDS: list[int] = [11, 12]
CREATED_AT: datetime = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _stored(name: str, special_type: str | None = None, system_type: bool = False) -> dict[str, Any]:
    """A stored Type as the seeding reads it"""
    return {
        TypeSchemaKey.NAME.value: name,
        TypeSchemaKey.SPECIAL_TYPE.value: special_type,
        TypeSchemaKey.SYSTEM_TYPE.value: system_type,
    }


def _manager(stored: list[dict[str, Any]]) -> MagicMock:
    """A Types manager whose find answers the stored Types and whose counter answers RESERVED_IDS"""
    manager: MagicMock = MagicMock()
    manager.find.return_value = stored
    manager.reserve_public_ids.side_effect = lambda amount: RESERVED_IDS[:amount]

    return manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    free_type_name                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_free_name_is_kept() -> None:
    """No Type holds it: the name itself"""
    assert free_type_name(PERSON_NAME, {'server'}) == PERSON_NAME


def test_a_taken_name_gets_the_first_free_suffix_from_two() -> None:
    """person taken -> person_2; person_2 taken too -> person_3"""
    assert free_type_name(PERSON_NAME, {PERSON_NAME}) == f'{PERSON_NAME}_2'
    assert free_type_name(PERSON_NAME, {PERSON_NAME, f'{PERSON_NAME}_2'}) == f'{PERSON_NAME}_3'

# -------------------------------------------------------------------------------------------------------------------- #
#                                              plan_default_person_types                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_markers_with_default_counts_system_types_only() -> None:
    """An ordinary Type carrying PERSON is no default; a system Type without a marker names none"""
    stored = [
        _stored('a', SpecialType.PERSON.value),
        _stored('b', SpecialType.PERSON_GROUP.value, system_type=True),
        _stored('c', None, system_type=True),
    ]

    assert markers_with_default(stored) == {SpecialType.PERSON_GROUP.value}


def test_an_empty_database_plans_both_defaults_under_their_names() -> None:
    """PERSON first, then PERSON_GROUP"""
    assert plan_default_person_types([]) == [(SpecialType.PERSON, PERSON_NAME), (SpecialType.PERSON_GROUP, GROUP_NAME)]


def test_both_defaults_stored_plans_nothing() -> None:
    """Seeding again changes nothing"""
    stored = [_stored('x', SpecialType.PERSON.value, True), _stored('y', SpecialType.PERSON_GROUP.value, True)]

    assert not plan_default_person_types(stored)


def test_an_ordinary_type_carrying_the_marker_does_not_count_and_its_name_is_avoided() -> None:
    """A user's Type named person carrying PERSON: the default is still planned, as person_2"""
    stored = [_stored(PERSON_NAME, SpecialType.PERSON.value), _stored('y', SpecialType.PERSON_GROUP.value, True)]

    assert plan_default_person_types(stored) == [(SpecialType.PERSON, f'{PERSON_NAME}_2')]


def test_the_planned_names_do_not_collide_with_each_other() -> None:
    """A stored Type named person_group_2 is avoided as well; the two planned names stay apart"""
    stored = [_stored(PERSON_NAME), _stored(GROUP_NAME), _stored(f'{GROUP_NAME}_2')]

    assert plan_default_person_types(stored) == [
        (SpecialType.PERSON, f'{PERSON_NAME}_2'), (SpecialType.PERSON_GROUP, f'{GROUP_NAME}_3'),
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_default_person_type                                               #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('marker, summary_field', [
    (SpecialType.PERSON, PersonField.DISPLAY_NAME.value),
    (SpecialType.PERSON_GROUP, PersonGroupField.NAME.value),
], ids=str)
def test_the_document_is_a_system_type_of_its_marker(marker: SpecialType, summary_field: str) -> None:
    """System Type, system author, no child locations, summary and CI Explorer label on the name field"""
    document = build_default_person_type(marker, 'chosen', 7, CREATED_AT)

    assert (document[TypeSchemaKey.PUBLIC_ID.value], document[TypeSchemaKey.NAME.value]) == (7, 'chosen')
    assert document[TypeSchemaKey.SPECIAL_TYPE.value] == marker.value
    assert document[TypeSchemaKey.SYSTEM_TYPE.value] is True
    assert document[TypeSchemaKey.AUTHOR_ID.value] == SYSTEM_AUTHOR_ID
    assert document[TypeSchemaKey.CREATION_TIME.value] == CREATED_AT
    assert document[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is False
    assert document[TypeSchemaKey.CI_EXPLORER_LABEL.value] == summary_field
    assert document[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.SUMMARY.value] == {
        TypeSchemaKey.FIELDS.value: [summary_field],
    }


@pytest.mark.parametrize('marker', [SpecialType.PERSON, SpecialType.PERSON_GROUP], ids=str)
def test_the_document_reads_back_unchanged_and_keeps_the_structure_rules(marker: SpecialType) -> None:
    """The stored shape the model writes (inactive ACL included), every value a plain string, a legal structure"""
    document = build_default_person_type(marker, 'chosen', 7, CREATED_AT)

    assert CmdbType.to_json(CmdbType.from_data(document)) == document
    assert document[TypeSchemaKey.ACL.value][AclKey.ACTIVATED.value] is False
    assert validate_type_structure(document) is None
    assert all(type(field[FieldKey.TYPE.value]) is str for field in document[TypeSchemaKey.FIELDS.value])


def test_each_document_is_built_anew() -> None:
    """Two builds share no list - changing one leaves the other alone"""
    first = build_default_person_type(SpecialType.PERSON, 'a', 1)
    second = build_default_person_type(SpecialType.PERSON, 'b', 2)
    first[TypeSchemaKey.FIELDS.value].clear()

    assert second[TypeSchemaKey.FIELDS.value]

# -------------------------------------------------------------------------------------------------------------------- #
#                                              seed_default_person_types                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_seeding_with_both_defaults_reserves_and_writes_nothing() -> None:
    """One projected read, then nothing"""
    manager = _manager([_stored('x', SpecialType.PERSON.value, True),
                        _stored('y', SpecialType.PERSON_GROUP.value, True)])

    assert not seed_default_person_types(manager, MagicMock(spec=WriteLedger))

    manager.find.assert_called_once_with(criteria={}, projection=SEED_PROJECTION)
    manager.reserve_public_ids.assert_not_called()
    manager.insert_many.assert_not_called()


def test_seeding_stores_the_missing_defaults_under_reserved_ids() -> None:
    """Both missing: two ids reserved in one call, both documents inserted in one batch keeping them"""
    manager = _manager([])

    assert seed_default_person_types(manager) == RESERVED_IDS

    manager.reserve_public_ids.assert_called_once_with(2)
    documents: list[dict[str, Any]] = manager.insert_many.call_args.args[0]
    assert [(doc[TypeSchemaKey.PUBLIC_ID.value], doc[TypeSchemaKey.SPECIAL_TYPE.value]) for doc in documents] == [
        (11, SpecialType.PERSON.value), (12, SpecialType.PERSON_GROUP.value),
    ]
    assert manager.insert_many.call_args.kwargs == {'skip_public': True}


def test_seeding_records_the_batch_on_the_ledger_before_the_insert() -> None:
    """The undo deletes exactly the reserved ids; recorded first, so a failed insert is still covered"""
    manager = _manager([_stored('x', SpecialType.PERSON.value, True)])
    parent: MagicMock = MagicMock()
    parent.attach_mock(manager.insert_many, 'insert_many')
    ledger: MagicMock = MagicMock(spec=WriteLedger)
    parent.attach_mock(ledger.inserted_where, 'inserted_where')

    assert seed_default_person_types(manager, ledger) == [11]

    assert [entry[0] for entry in parent.mock_calls] == ['inserted_where', 'insert_many']
    ledger.inserted_where.assert_called_once_with(manager, {TypeSchemaKey.PUBLIC_ID.value: {'$in': [11]}})


def test_a_failed_insert_raises() -> None:
    """The caller decides - the bring-up tolerates a lost race, an import undoes its ledger"""
    manager = _manager([])
    manager.insert_many.side_effect = RuntimeError('refused')

    with pytest.raises(RuntimeError):
        seed_default_person_types(manager)
