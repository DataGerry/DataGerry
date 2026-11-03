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
Integration tests for the ProtectionGoal name rule against a real MongoDB

The unique ``name`` index ``IsmsProtectionGoal.INDEX_KEYS`` declares is built on the bound collection, then:

  - ``find_name_holder`` answers the holder of an exact name, and None for another spelling
  - a second insert of a taken name is refused by the index, as a manager insert error caused by a duplicate key
  - ``insert_protection_goal`` answers that refusal with the name rule's 400
  - the risk import's ``insert_or_reuse_named_item`` resolves it to the stored goal, inserting nothing
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentDuplicateKeyError
from cmdb.errors.manager.protection_goal_manager import ProtectionGoalManagerInsertError
from cmdb.manager.isms_manager.protection_goal_manager import ProtectionGoalManager
from cmdb.models.isms_model import IsmsProtectionGoal
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey
from cmdb.utils import find_cause
from cmdb.interface.rest_api.routes.importer_routes.importer_isms_routes import insert_or_reuse_named_item
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import PROTECTION_GOAL_NAME_TAKEN_MSG
from cmdb.interface.rest_api.routes.isms_routes.protection_goal_helper import insert_protection_goal
# -------------------------------------------------------------------------------------------------------------------- #

STORED_ID: int = 99691
NAME: str = 'T416 integration'
OTHER_SPELLING: str = 't416 INTEGRATION'
HTTP_BAD_REQUEST: int = 400


def _new_goal(name: str = NAME) -> dict[str, Any]:
    """An insertable goal"""
    return {ProtectionGoalKey.NAME.value: name, ProtectionGoalKey.PREDEFINED.value: False}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """One stored goal and the unique name index; both removed again"""
    collection = database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({ProtectionGoalKey.NAME.value: {'$in': [NAME, OTHER_SPELLING]}})

    _purge()
    collection.insert_one({**_new_goal(), ProtectionGoalKey.PUBLIC_ID.value: STORED_ID})
    database_manager.create_indexes(IsmsProtectionGoal.COLLECTION, database_name, IsmsProtectionGoal.get_index_keys())

    yield ProtectionGoalManager(database_manager)

    database_manager.drop_index(IsmsProtectionGoal.COLLECTION, database_name, ProtectionGoalKey.NAME.value)
    _purge()


def _count(database_manager: MongoDatabaseManager, database_name: str, name: str) -> int:
    """How many goals carry the name"""
    return database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name).count_documents(
        {ProtectionGoalKey.NAME.value: name},
    )


def test_the_index_is_unique_on_the_name(manager: ProtectionGoalManager, database_manager: MongoDatabaseManager,
                                         database_name: str) -> None:
    """Built from INDEX_KEYS"""
    indexes: dict[str, Any] = database_manager.get_collection(
        IsmsProtectionGoal.COLLECTION, database_name,
    ).index_information()

    assert manager is not None
    assert indexes[ProtectionGoalKey.NAME.value]['unique'] is True


def test_find_name_holder_compares_exactly(manager: ProtectionGoalManager) -> None:
    """The stored goal for its name, nobody for another spelling"""
    assert manager.find_name_holder(NAME) == STORED_ID
    assert manager.find_name_holder(OTHER_SPELLING) is None


def test_a_second_insert_of_a_name_is_refused_by_the_index(manager: ProtectionGoalManager,
                                                           database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
    """A manager insert error caused by a duplicate key - nothing stored"""
    with pytest.raises(ProtectionGoalManagerInsertError) as exc_info:
        manager.insert_item(_new_goal())

    assert find_cause(exc_info.value, DocumentDuplicateKeyError) is not None
    assert _count(database_manager, database_name, NAME) == 1


def test_the_route_helper_answers_the_refusal_with_the_name_rules_400(manager: ProtectionGoalManager) -> None:
    """The same message the pre-check gives"""
    with pytest.raises(HTTPException) as exc_info:
        insert_protection_goal(manager, _new_goal())

    assert exc_info.value.code == HTTP_BAD_REQUEST
    assert exc_info.value.description == PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=NAME)


def test_the_risk_import_reuses_the_stored_goal(manager: ProtectionGoalManager,
                                                database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The name a concurrent write took resolves to that goal"""
    reused: int = insert_or_reuse_named_item(
        manager, ProtectionGoalKey, NAME, {ProtectionGoalKey.PREDEFINED.value: False},
    )

    assert reused == STORED_ID
    assert _count(database_manager, database_name, NAME) == 1


def test_another_spelling_is_inserted(manager: ProtectionGoalManager, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
    """Names compare exactly - the index allows it"""
    new_id: int = insert_protection_goal(manager, _new_goal(OTHER_SPELLING))

    assert new_id != STORED_ID
    assert _count(database_manager, database_name, OTHER_SPELLING) == 1
