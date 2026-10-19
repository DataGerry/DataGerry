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
Integration tests for the narrowed rack-mount, object-relation, person and reference reads against a real MongoDB

Each manager catches only the typed failure of its database call. What it catches has to be what a real failure
raises, or a database failure would slip past it as an unhandled error (the route's 500 where a 400 is meant).
Nothing is patched: MongoDB itself refuses an unknown query operator or a sort path naming one
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import ObjectRelationRole
from cmdb.models.person_model import CmdbPerson
from cmdb.utils import find_cause

from cmdb.errors.database import DocumentUpdateError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerIterationError
from cmdb.errors.manager.persons_manager import PersonsManagerDeleteError
from cmdb.errors.manager.rack_mounts_manager import RackMountsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

# A query operator MongoDB does not know - it refuses the read or write itself
UNKNOWN_OPERATOR: dict[str, Any] = {'$no_such_operator': 1}
# A sort path naming an operator, which MongoDB refuses
OPERATOR_SORT_PATH: str = '$no_such_path'

RACK_ID: int = 97601
OBJECT_ID: int = 97602
RELATION_ID: int = 97603
PERSON_ID: int = 97604


def test_a_refused_mount_read_is_the_get_error(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """get_mounts_of_rack: the real find's BaseManagerGetError is wrapped as the manager's get error"""
    manager = RackMountsManager(database_manager, database_name)

    with pytest.raises(RackMountsManagerGetError) as caught:
        manager.get_mounts_of_rack(RACK_ID, area=UNKNOWN_OPERATOR)

    assert find_cause(caught.value, BaseManagerGetError) is not None


def test_a_refused_tab_aggregation_is_the_iteration_error(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """get_relation_tabs: the real aggregation's failure is the manager's iteration error"""
    manager = ObjectRelationsManager(database_manager, database_name)

    with pytest.raises(ObjectRelationsManagerIterationError) as caught:
        manager.get_relation_tabs(UNKNOWN_OPERATOR)

    assert find_cause(caught.value, BaseManagerIterationError) is not None


def test_a_refused_tab_instance_read_is_the_iteration_error(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """get_relation_tab_instances: a sort MongoDB refuses fails the page read, which is the iteration error"""
    manager = ObjectRelationsManager(database_manager, database_name)

    with pytest.raises(ObjectRelationsManagerIterationError) as caught:
        manager.get_relation_tab_instances(OBJECT_ID, RELATION_ID, ObjectRelationRole.PARENT.value,
                                           sort=OPERATOR_SORT_PATH)

    assert find_cause(caught.value, BaseManagerGetError) is not None


def test_a_refused_reference_read_is_the_iteration_error(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """references: the real id read's failure is the manager's iteration error"""
    manager = ObjectsManager(database_manager, database_name)
    target = CmdbObject.from_data({'public_id': OBJECT_ID, 'type_id': RACK_ID, 'author_id': 1, 'version': '1.0.0',
                                   'active': True, 'fields': []})

    with pytest.raises(ObjectsManagerIterationError) as caught:
        manager.references(target, [{'$match': {'public_id': UNKNOWN_OPERATOR}}], 0, 0, 'public_id', 1)

    assert find_cause(caught.value, BaseManagerIterationError) is not None


def test_a_refused_cascade_write_is_the_delete_error_and_keeps_the_person(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """delete_with_follow_up: the cascade's real write failure is the delete error, and the person stays"""
    persons = database_manager.get_collection(CmdbPerson.COLLECTION, database_name)
    persons.delete_many({'public_id': PERSON_ID})
    persons.insert_one({'public_id': PERSON_ID, 'display_name': 'Narrowed', 'first_name': 'N', 'last_name': 'N',
                        'phone_number': '', 'email': '', 'groups': []})

    try:
        with pytest.raises(PersonsManagerDeleteError) as caught:
            PersonsManager(database_manager, database_name).delete_with_follow_up(UNKNOWN_OPERATOR)

        assert find_cause(caught.value, DocumentUpdateError) is not None
        assert persons.find_one({'public_id': PERSON_ID}) is not None
    finally:
        persons.delete_many({'public_id': PERSON_ID})
