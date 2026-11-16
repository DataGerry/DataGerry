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
Persons and person groups for the ISMS tests - objects of a Type carrying PERSON / PERSON_GROUP

The ISMS write check, the naming and the reports read a person as an object whose ``special_type`` is PERSON, its name
from the label field (``display_name`` / ``name``). ``seed_person_objects`` stores the two test Types (ordinary Types,
ACL off) and one object per id; ``purge_person_objects`` removes them again
"""
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_selector.person_selector_constants import LABEL_FIELD_BY_KIND
from tests.utils.ipam_doc_builders import make_object_doc
# -------------------------------------------------------------------------------------------------------------------- #

# The two test Types - far above what any test seeds otherwise
TEST_PERSON_TYPE_ID: int = 99901
TEST_PERSON_GROUP_TYPE_ID: int = 99902
TEST_TYPE_IDS: dict[SpecialType, int] = {
    SpecialType.PERSON: TEST_PERSON_TYPE_ID,
    SpecialType.PERSON_GROUP: TEST_PERSON_GROUP_TYPE_ID,
}


def person_object_doc(public_id: int, marker: SpecialType, name: str | None) -> dict[str, Any]:
    """
    A person or group object of the test Type, its label field holding the name

    Args:
        public_id (int): The object id
        marker (SpecialType): PERSON or PERSON_GROUP
        name (str | None): The display name

    Returns:
        dict[str, Any]: The object document
    """
    document: dict[str, Any] = make_object_doc(
        public_id, TEST_TYPE_IDS[marker], [{'name': LABEL_FIELD_BY_KIND[marker], 'value': name, 'type': 'text'}],
    )
    document['special_type'] = marker.value

    return document


def seed_person_objects(database_manager: MongoDatabaseManager, database_name: str,
                        persons: dict[int, str | None] | None = None,
                        groups: dict[int, str | None] | None = None) -> None:
    """
    Stores the two test Types and the person / group objects, replacing what an earlier test left

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The database
        persons (dict[int, str | None] | None): Name by person object id
        groups (dict[int, str | None] | None): Name by group object id
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    for marker, type_id in TEST_TYPE_IDS.items():
        document = build_default_person_type(marker, f'test-{marker.value.lower()}-{type_id}', type_id)
        document[TypeSchemaKey.SYSTEM_TYPE.value] = False
        types.replace_one({'public_id': type_id}, document, upsert=True)

    for marker, entries in ((SpecialType.PERSON, persons or {}), (SpecialType.PERSON_GROUP, groups or {})):
        for public_id, name in entries.items():
            objects.replace_one({'public_id': public_id}, person_object_doc(public_id, marker, name), upsert=True)


def purge_person_objects(database_manager: MongoDatabaseManager, database_name: str, object_ids: list[int]) -> None:
    """
    Removes the person / group objects and the two test Types

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The database
        object_ids (list[int]): The object ids to remove
    """
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': object_ids}})
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': list(TEST_TYPE_IDS.values())}})
