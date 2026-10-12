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
Seeds persons and person groups - CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes - for integration and
functional tests

At most one CmdbType per SpecialType exists in an installation, and several test modules need persons, so
``ensure_person_types`` reuses the types already stored and only inserts them (from the predefined blueprints,
under fixed ids) when none exists. The objects are written straight into the object collection under the
caller's ids; ``remove_objects`` deletes them again. The types are left in place for the next module
"""
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.person_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.schemas.person_schema import get_person_group_schema, get_person_schema

from tests.utils.ipam_doc_builders import make_object_doc, make_type_doc
from tests.utils.person_stubs import plain, selection
# -------------------------------------------------------------------------------------------------------------------- #

SEED_PERSON_TYPE_ID: int = 95001
SEED_PERSON_GROUP_TYPE_ID: int = 95002


def _ensure_type(database_manager: MongoDatabaseManager, database_name: str, special_type: str, type_id: int,
                 name: str, blueprint: dict[str, Any]) -> int:
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    existing: dict[str, Any] | None = types.find_one({'special_type': special_type})

    if existing:
        return existing['public_id']

    schema: dict[str, Any] = plain(blueprint)
    types.insert_one(make_type_doc(
        type_id, name, special_type=special_type, fields=schema['fields'], sections=schema['sections'],
    ))

    return type_id


def ensure_person_types(database_manager: MongoDatabaseManager, database_name: str) -> tuple[int, int]:
    """
    The PERSON and PERSON_GROUP CmdbTypes, inserted when missing

    Returns:
        tuple[int, int]: (person type id, person group type id)
    """
    return (
        _ensure_type(database_manager, database_name, 'PERSON', SEED_PERSON_TYPE_ID, 'dg_person', get_person_schema()),
        _ensure_type(database_manager, database_name, 'PERSON_GROUP', SEED_PERSON_GROUP_TYPE_ID, 'dg_person_group',
                     get_person_group_schema()),
    )


def person_doc(public_id: int, type_id: int, display_name: str, **values: str) -> dict[str, Any]:
    """
    A PERSON object document

    Args:
        public_id (int): The object id
        type_id (int): The PERSON type
        display_name (str): The full name
        **values: Further field values by PersonField name, e.g. first_name='Ada'
    """
    fields: list[dict[str, Any]] = [{'name': PersonField.DISPLAY_NAME.value, 'value': display_name}]
    fields += [{'name': PersonField[key.upper()].value, 'value': value} for key, value in values.items()]

    return make_object_doc(public_id, type_id, fields)


def group_doc(public_id: int, type_id: int, name: str, member_ids: list[int] | None = None,
              email: str = '') -> dict[str, Any]:
    """A PERSON_GROUP object document listing the given persons in its MEMBERS field"""
    return make_object_doc(public_id, type_id, [
        {'name': PersonGroupField.NAME.value, 'value': name},
        {'name': PersonGroupField.EMAIL.value, 'value': email},
        {'name': PersonGroupField.MEMBERS.value, 'type': 'person',
         'value': [selection('PERSON', member_id) for member_id in member_ids or []]},
    ])


def insert_objects(database_manager: MongoDatabaseManager, database_name: str, *documents: dict[str, Any]) -> None:
    """Writes the documents, replacing any left over under the same ids"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    remove_objects(database_manager, database_name, [document['public_id'] for document in documents])
    objects.insert_many([dict(document) for document in documents])


def remove_objects(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Deletes the objects with the given ids"""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': list(public_ids)}},
    )
