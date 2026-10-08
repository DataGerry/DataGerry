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
Integration test of the object-delete relation cascade against a relation created while it runs

The cascade reads the relations of the deleted object, deletes them and logs each one. A relation another writer
creates between that read and the delete must neither be left on the deleted object nor be removed without a log.
The interleaving is forced: the step between the read and the delete (preparing the logs) inserts the late relation
into the real collection the first time it runs. Everything else - both managers, the query, the delete, the id
reservation and the log insert - is real
"""
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationLogsManager, ObjectRelationsManager
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.log_model.object_relation_log_constants import ObjectRelationLogKey
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects import objects_side_effects_helper as cascade
# -------------------------------------------------------------------------------------------------------------------- #

DELETED_OBJECT_ID: int = 9561
OTHER_OBJECT_ID: int = 9562
FIRST_RELATION_ID: int = 9571
LATE_RELATION_ID: int = 9572
RELATION_IDS: list[int] = [FIRST_RELATION_ID, LATE_RELATION_ID]
RELATION_DEFINITION_ID: int = 9570
AUTHOR_ID: int = 1
DELETE_ACTION: str = 'DELETE'


def _relation(public_id: int) -> dict[str, Any]:
    """A relation of the deleted object (as parent) to the other object."""
    return {
        ObjectRelationKey.PUBLIC_ID.value: public_id,
        'relation_id': RELATION_DEFINITION_ID,
        ObjectRelationKey.RELATION_PARENT_ID.value: DELETED_OBJECT_ID,
        ObjectRelationKey.RELATION_CHILD_ID.value: OTHER_OBJECT_ID,
        'field_values': [],
    }


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[Any, Any]]:
    """The relation and relation-log collections, with one relation of the deleted object seeded."""
    relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)
    relations.delete_many({ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}})
    logs.delete_many({ObjectRelationLogKey.OBJECT_RELATION_ID.value: {'$in': RELATION_IDS}})
    relations.insert_one(_relation(FIRST_RELATION_ID))

    yield relations, logs

    relations.delete_many({ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}})
    logs.delete_many({ObjectRelationLogKey.OBJECT_RELATION_ID.value: {'$in': RELATION_IDS}})


def _run_with_a_late_relation(database_manager: MongoDatabaseManager, relations: Any) -> None:
    """Runs the real cascade, inserting the late relation between its first read and its first delete."""
    managers = {
        ManagerType.OBJECT_RELATIONS: ObjectRelationsManager(database_manager),
        ManagerType.OBJECT_RELATION_LOGS: ObjectRelationLogsManager(database_manager),
    }
    prepare = cascade.prepare_relation_delete_logs
    rounds: list[int] = []

    def _prepare_then_race(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if not rounds:
            relations.insert_one(_relation(LATE_RELATION_ID))
        rounds.append(1)

        return prepare(*args, **kwargs)

    request_user = MagicMock()
    request_user.get_public_id.return_value = AUTHOR_ID
    request_user.get_display_name.return_value = 'integration'

    with patch(f'{cascade.__name__}.ManagerProvider.get_manager', side_effect=lambda kind, _user: managers[kind]), \
         patch(f'{cascade.__name__}.prepare_relation_delete_logs', side_effect=_prepare_then_race):
        cascade.handle_delete_invalid_object_relations(request_user, [DELETED_OBJECT_ID])


def test_a_relation_created_mid_cascade_is_deleted(database_manager: MongoDatabaseManager, collections) -> None:
    """No relation of the deleted object survives the cascade"""
    relations, _logs = collections

    _run_with_a_late_relation(database_manager, relations)

    assert relations.count_documents({ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}}) == 0


def test_every_deleted_relation_is_logged_exactly_once(database_manager: MongoDatabaseManager, collections) -> None:
    """The late relation gets its own DELETE log - before, it was deleted by the query and never logged"""
    relations, logs = collections

    _run_with_a_late_relation(database_manager, relations)

    logged = sorted(
        log[ObjectRelationLogKey.OBJECT_RELATION_ID.value]
        for log in logs.find({ObjectRelationLogKey.OBJECT_RELATION_ID.value: {'$in': RELATION_IDS},
                              ObjectRelationLogKey.ACTION.value: DELETE_ACTION})
    )
    assert logged == RELATION_IDS
