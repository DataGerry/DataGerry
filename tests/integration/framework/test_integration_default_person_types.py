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
Integration tests of the default person Types against a real MongoDB

Pinned on a scratch database of its own, behind the indexes CmdbType declares: the first boot pass stores both
defaults (system Types, the default names, ids from the counter); further boots store nothing; a default that went
missing is stored again; a taken name is avoided; the index refuses a second system Type of a marker while ordinary
Types may carry it any number of times; a ledgered seeding is undone exactly; the default PERSON Type stores
exactly the base fields; and a field a person Type adds is judged by nobody's name rule
"""
from typing import Any, Iterator

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.type_model import CmdbType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.object_model import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import DefaultPersonType, PersonField
from cmdb.framework.object_invariants import enforce_object_write_invariants
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.default_person_types import build_default_person_type, seed_default_person_types
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-default-person-types'
PUBLIC_ID_KEY: str = 'public_id'
BOOT_COUNT: int = 3
TAKEN_ID: int = 9
OWN_FIELD: str = 'user'
OWN_VALUE: int = 4


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """An empty scratch database whose Types collection carries the production indexes, dropped before and after"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch][CmdbType.COLLECTION].create_indexes(CmdbType.get_index_keys())

    yield scratch

    client.drop_database(scratch)


def _boot(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """One boot pass of the framework collections - what every startup runs"""
    CollectionValidator(scratch, database_manager).init_framework_collections()


def _types(database_manager: MongoDatabaseManager, scratch: str) -> Any:
    """The scratch database's Types collection"""
    return database_manager.get_collection(CmdbType.COLLECTION, scratch)


def _defaults(database_manager: MongoDatabaseManager, scratch: str) -> list[tuple[int, str, str]]:
    """The stored system Types as (public_id, name, marker), by public_id"""
    return [
        (row[PUBLIC_ID_KEY], row[TypeSchemaKey.NAME.value], row[TypeSchemaKey.SPECIAL_TYPE.value])
        for row in _types(database_manager, scratch).find({TypeSchemaKey.SYSTEM_TYPE.value: True},
                                                          sort=[(PUBLIC_ID_KEY, 1)])
    ]


def test_the_first_boot_stores_both_defaults(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Ids from the counter, the default names, readable as CmdbTypes"""
    _boot(database_manager, scratch)

    assert _defaults(database_manager, scratch) == [
        (1, DefaultPersonType.PERSON_NAME.value, SpecialType.PERSON.value),
        (2, DefaultPersonType.PERSON_GROUP_NAME.value, SpecialType.PERSON_GROUP.value),
    ]
    assert all(CmdbType.from_data(row) for row in _types(database_manager, scratch).find())


def test_further_boots_store_nothing(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Re-run safe: however many boots, two defaults"""
    for _ in range(BOOT_COUNT):
        _boot(database_manager, scratch)

    assert len(_defaults(database_manager, scratch)) == 2


def test_a_missing_default_is_stored_again(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Only the missing one, under the next id"""
    _boot(database_manager, scratch)
    _types(database_manager, scratch).delete_one({TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.PERSON_GROUP.value})

    _boot(database_manager, scratch)

    assert _defaults(database_manager, scratch) == [
        (1, DefaultPersonType.PERSON_NAME.value, SpecialType.PERSON.value),
        (3, DefaultPersonType.PERSON_GROUP_NAME.value, SpecialType.PERSON_GROUP.value),
    ]


def test_a_taken_name_is_avoided(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """A user's Type named person stays; the default becomes person_2"""
    _types(database_manager, scratch).insert_one(make_type_doc(TAKEN_ID, DefaultPersonType.PERSON_NAME.value))

    seed_default_person_types(TypesManager(database_manager, scratch))

    assert [name for _id, name, _marker in _defaults(database_manager, scratch)] == [
        f'{DefaultPersonType.PERSON_NAME.value}_2', DefaultPersonType.PERSON_GROUP_NAME.value,
    ]


def test_the_index_holds_one_default_per_marker(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """A second system PERSON Type is refused; ordinary PERSON Types are not limited"""
    types = _types(database_manager, scratch)
    seed_default_person_types(TypesManager(database_manager, scratch))

    with pytest.raises(DuplicateKeyError):
        types.insert_one(build_default_person_type(SpecialType.PERSON, 'second-default', 10))

    types.insert_many([make_type_doc(11, 'person-a', special_type=SpecialType.PERSON.value),
                       make_type_doc(12, 'person-b', special_type=SpecialType.PERSON.value)])

    assert types.count_documents({TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.PERSON.value}) == 3


def test_a_ledgered_seeding_is_undone_exactly(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """The undo removes the seeded Types and nothing else"""
    types = _types(database_manager, scratch)
    types.insert_one(make_type_doc(TAKEN_ID, 'kept'))
    ledger: WriteLedger = WriteLedger()

    assert len(seed_default_person_types(TypesManager(database_manager, scratch), ledger)) == 2
    assert not ledger.undo()

    assert [row[TypeSchemaKey.NAME.value] for row in types.find()] == ['kept']


def test_the_default_person_type_stores_exactly_the_base_fields(
        database_manager: MongoDatabaseManager, scratch: str) -> None:
    """The fields and the one section of the default PERSON Type are the PERSON base fields - nothing else"""
    seed_default_person_types(TypesManager(database_manager, scratch))
    stored = _types(database_manager, scratch).find_one({
        TypeSchemaKey.SYSTEM_TYPE.value: True, TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.PERSON.value,
    })
    base_fields: list[str] = [field.value for field in PersonField]

    sections: list[dict[str, Any]] = stored[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.SECTIONS.value]

    assert [field[FieldKey.NAME.value] for field in stored[TypeSchemaKey.FIELDS.value]] == base_fields
    assert [section[SectionKey.FIELDS.value] for section in sections] == [base_fields]


def test_a_person_may_hold_any_value_in_a_field_of_its_own(
        database_manager: MongoDatabaseManager, scratch: str) -> None:
    """A field a person Type adds is that Type's own - the write invariants judge no person field by its name"""
    seed_default_person_types(TypesManager(database_manager, scratch))
    person_type: int = _defaults(database_manager, scratch)[0][0]
    candidate: dict[str, Any] = {
        CmdbObjectKey.TYPE_ID.value: person_type,
        CmdbObjectKey.FIELDS.value: [
            {CmdbObjectFieldKey.NAME.value: OWN_FIELD, CmdbObjectFieldKey.VALUE.value: OWN_VALUE},
        ],
    }

    objects_manager = ObjectsManager(database_manager, scratch)
    types_manager = TypesManager(database_manager, scratch)

    assert enforce_object_write_invariants(objects_manager, types_manager, candidate) is None
