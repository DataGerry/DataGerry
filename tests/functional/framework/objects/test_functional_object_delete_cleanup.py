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
Functional coverage of an object delete whose cleanup steps fail after the object is gone

Once the object is deleted nothing undoes that, so a failing cleanup step must not answer the delete as failed. Over
the single and the bulk route: each step failing in turn - with the error its own manager really raises - answers 200,
the object is gone, the steps after it still run (the deletion log is written) and the failure is logged under
DELETE_CLEANUP_INCOMPLETE_MARKER naming the step. A programming error in a step still answers 500. On the bulk route a
target that fails at its own delete stops the loop, and the targets deleted before it still get their selection-wide
clean-up
"""
from http import HTTPStatus
from typing import Any, Callable, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.manager.object_groups_manager import ObjectGroupsManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_relation_log_constants import ObjectRelationLogKey
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import ObjectLogKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    DELETE_CLEANUP_INCOMPLETE_MARKER,
    DeleteCleanupStep,
)
from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.media_files_manager import MediaFileManagerUpdateError
from cmdb.errors.manager.objects_manager import ObjectsManagerDeleteError, ObjectsManagerUpdateError
from cmdb.errors.manager.ports_manager import PortsManagerGetError
from cmdb.errors.manager.rack_mounts_manager import RackMountsManagerDeleteError
from tests.functional.framework.objects.objects_route_helpers import (
    ROUTE_URL,
    drop_object,
    insert_object_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_ID: int = 9481
SECOND_ID: int = 9482
BYSTANDER_ID: int = 9483
OBJECT_IDS: list[int] = [FIRST_ID, SECOND_ID, BYSTANDER_ID]
FIRST_RELATION_ID: int = 9491
SECOND_RELATION_ID: int = 9492
RELATION_IDS: list[int] = [FIRST_RELATION_ID, SECOND_RELATION_ID]
RELATION_DEFINITION_ID: int = 9490
OBJECT_VALUE: str = 'delete-cleanup'

# step -> (the manager, the method its step calls, the error that method really raises)
FAILING_STEPS: list[tuple[DeleteCleanupStep, type, str, Exception]] = [
    (DeleteCleanupStep.REFERENCES, ObjectsManager, 'delete_all_object_references', ObjectsManagerUpdateError('x')),
    (DeleteCleanupStep.OBJECT_GROUPS, ObjectGroupsManager, 'update_many_pull', BaseManagerUpdateError('x')),
    (DeleteCleanupStep.RELATIONS, ObjectRelationsManager, 'find', BaseManagerGetError('x')),
    (DeleteCleanupStep.ATTACHMENTS, MediaFilesManager, 'detach_objects', MediaFileManagerUpdateError('x')),
    (DeleteCleanupStep.RACK, RackMountsManager, 'delete_mount_of_object', RackMountsManagerDeleteError('x')),
    (DeleteCleanupStep.PORTS, PortsManager, 'get_port_kinds_of_object', PortsManagerGetError('x')),
]


def _raiser(error: Exception) -> Callable[..., Any]:
    """A replacement that always raises the given error"""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """Three objects and a relation of each of the first two to the bystander; removed - with every log - afterwards"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    relation_logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)

    def _purge() -> None:
        relations.delete_many({ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}})
        # The relation cascade writes a DELETE log per removed relation; none may outlive the test
        relation_logs.delete_many({ObjectRelationLogKey.OBJECT_RELATION_ID.value: {'$in': RELATION_IDS}})
        logs.delete_many({ObjectLogKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})
        for object_id in OBJECT_IDS:
            drop_object(database_manager, database_name, object_id)

    _purge()

    for object_id in OBJECT_IDS:
        insert_object_doc(database_manager, database_name, object_id, OBJECT_VALUE)

    relations.insert_many([
        {ObjectRelationKey.PUBLIC_ID.value: relation_id, 'relation_id': RELATION_DEFINITION_ID,
         ObjectRelationKey.RELATION_PARENT_ID.value: parent_id,
         ObjectRelationKey.RELATION_CHILD_ID.value: BYSTANDER_ID, 'field_values': []}
        for relation_id, parent_id in ((FIRST_RELATION_ID, FIRST_ID), (SECOND_RELATION_ID, SECOND_ID))
    ])

    yield {'objects': objects, 'relations': relations, 'logs': logs}

    _purge()


def _deletion_logged(seeded: dict[str, Any], object_id: int) -> bool:
    """Whether the object's DELETE change-log entry was written"""
    return seeded['logs'].count_documents({
        ObjectLogKey.OBJECT_ID.value: object_id, ObjectLogKey.ACTION.value: LogAction.DELETE.value,
    }) == 1


def _stored_relations(seeded: dict[str, Any]) -> list[int]:
    """The seeded relations still stored"""
    return sorted(doc[ObjectRelationKey.PUBLIC_ID.value] for doc in seeded['relations'].find(
        {ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}}))


@pytest.mark.parametrize('step, manager, method, error', FAILING_STEPS,
                         ids=[step.value for step, *_rest in FAILING_STEPS])
def test_a_failing_step_of_the_single_delete_still_answers_success(
        rest_api, monkeypatch, caplog, seeded, step: DeleteCleanupStep, manager: type, method: str,
        error: Exception) -> None:
    """The object is gone, the deletion log is written after the failed step, the failure is logged by name"""
    monkeypatch.setattr(manager, method, _raiser(error))

    response = rest_api.delete(f'{ROUTE_URL}/{FIRST_ID}')

    assert response.status_code == HTTPStatus.OK
    assert seeded['objects'].count_documents({'public_id': FIRST_ID}) == 0
    assert _deletion_logged(seeded, FIRST_ID)
    assert f'{DELETE_CLEANUP_INCOMPLETE_MARKER} step={step.value} objects=[{FIRST_ID}]' in caplog.text


def test_a_failed_relation_step_leaves_the_relation_and_the_rest_runs(rest_api, monkeypatch, seeded) -> None:
    """What a failed step leaves behind is exactly its own work - the relation stays, nothing else is skipped"""
    monkeypatch.setattr(ObjectRelationsManager, 'find', _raiser(BaseManagerGetError('x')))

    assert rest_api.delete(f'{ROUTE_URL}/{FIRST_ID}').status_code == HTTPStatus.OK
    assert _stored_relations(seeded) == RELATION_IDS


def test_a_bug_in_a_cleanup_step_is_still_a_500(rest_api, monkeypatch, seeded) -> None:
    """Only a step's own typed errors are tolerated"""
    monkeypatch.setattr(ObjectGroupsManager, 'update_many_pull', _raiser(KeyError('bug')))

    assert rest_api.delete(f'{ROUTE_URL}/{FIRST_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert seeded['objects'].count_documents({'public_id': FIRST_ID}) == 0


@pytest.mark.parametrize('step, manager, method, error', FAILING_STEPS,
                         ids=[step.value for step, *_rest in FAILING_STEPS])
def test_a_failing_step_of_the_bulk_delete_still_answers_success(
        rest_api, monkeypatch, caplog, seeded, step: DeleteCleanupStep, manager: type, method: str,
        error: Exception) -> None:
    """Both targets are gone and acknowledged; both deletion logs are written"""
    monkeypatch.setattr(manager, method, _raiser(error))

    response = rest_api.delete(f'{ROUTE_URL}/delete/{FIRST_ID},{SECOND_ID}')

    assert response.status_code == HTTPStatus.OK
    assert sorted(response.get_json()['successfully']) == [FIRST_ID, SECOND_ID]
    assert seeded['objects'].count_documents({'public_id': {'$in': [FIRST_ID, SECOND_ID]}}) == 0
    assert _deletion_logged(seeded, FIRST_ID) and _deletion_logged(seeded, SECOND_ID)
    assert f'{DELETE_CLEANUP_INCOMPLETE_MARKER} step={step.value}' in caplog.text


def test_a_target_failing_at_its_delete_leaves_no_earlier_target_without_its_cleanup(
        rest_api, monkeypatch, seeded) -> None:
    """
    The loop stops at the failing target and its error reaches the caller - but the target deleted before it still
    loses its relation, the selection-wide clean-up having run in the route's `finally`
    """
    original_delete = ObjectsManager.delete_object

    def _second_fails(self, public_id: int, *args: Any, **kwargs: Any) -> Any:
        if public_id == SECOND_ID:
            raise ObjectsManagerDeleteError('the second target could not be deleted')
        return original_delete(self, public_id, *args, **kwargs)

    monkeypatch.setattr(ObjectsManager, 'delete_object', _second_fails)

    response = rest_api.delete(f'{ROUTE_URL}/delete/{FIRST_ID},{SECOND_ID}')

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert seeded['objects'].count_documents({'public_id': FIRST_ID}) == 0
    assert seeded['objects'].count_documents({'public_id': SECOND_ID}) == 1
    assert _stored_relations(seeded) == [SECOND_RELATION_ID]
