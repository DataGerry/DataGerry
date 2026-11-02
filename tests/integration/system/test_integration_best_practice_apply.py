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
Integration tests for applying best-practice models (``best_practice_helper.apply_best_practice_models``) against a
real MongoDB

The managers' tenant resolver is pointed at a scratch target holding only its database version and the groups; the
model is the best-practice fixture model, loaded by the real catalogue. Pinned: the model is imported and
``best_practice_model`` recorded with its id - read back as the offer reads it; the cached model is not changed by the
import; a second apply is refused and the first decision stays; a write that fails half-way is undone and records
nothing. The decision is the import's last write: when it fails the import is undone, an earlier decision is put back,
a temporary database error passes through unchanged (so a retry can succeed), and it is written while the
configuration lock is still held. Two models combined: the type they share is stored once, every reference of either
meets it, and a pair whose shared type differs writes nothing
"""
from copy import deepcopy
from http import HTTPStatus
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.framework.configuration_transfer import BestPracticeModel, load_catalogue
from cmdb.manager import SettingsManager
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.category_model import CmdbCategory
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper import apply_best_practice_models
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
    StartAssistantDecision,
    StartAssistantKey,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper import (
    build_decision_document,
    read_decision,
)
from cmdb.errors.database import DocumentNetworkError, DocumentUpdateError
from tests.utils.configuration_lock_seed import stored_configuration_lock
from tests.utils.best_practice_model_fixture import (
    COMPANY_NAME,
    COMPANY_TYPE_ID,
    CONTACT_NAME,
    CUSTOMER_NAME,
    CUSTOMER_TYPE_ID,
    EMPLOYER_FIELD,
    MODEL_DB_VERSION,
    SUPPLIER_FIELD,
    SUPPLIER_NAME,
    SUPPLIES_RELATION_NAME,
    model_document,
    second_model_document,
    second_model_meta,
    write_model_file,
)
# -------------------------------------------------------------------------------------------------------------------- #

pytestmark = pytest.mark.usefixtures('rest_api_app_context')

TARGET_SUFFIX: str = '-best-practice-apply-target'
MODEL_ID: str = 'clients'
SECOND_MODEL_ID: str = 'suppliers'
PUBLIC_ID: str = CmdbType.PUBLIC_ID_KEY
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_id=ADMIN_GROUP_ID)


@pytest.fixture(name='target')
def fixture_target(database_manager: MongoDatabaseManager, database_name: str,
                   monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A reset target recording the model file's version and holding the groups; the managers routed to it"""
    name: str = f'{database_name}{TARGET_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)
    client[name][CmdbUserGroup.COLLECTION].insert_many(list(client[database_name][CmdbUserGroup.COLLECTION].find()))
    SettingsManager(database_manager, name).write(UpdaterSetting.SECTION.value,
                                                  {UpdaterSetting.VERSION.value: MODEL_DB_VERSION})
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: name))

    yield client[name]

    client.drop_database(name)


@pytest.fixture(name='model')
def fixture_model(tmp_path: Path) -> BestPracticeModel:
    """The fixture model without licensed types, read by the real catalogue"""
    write_model_file(tmp_path, MODEL_ID, document=model_document(with_supernet=False))

    return load_catalogue(tmp_path).get(MODEL_ID)


def _type_ids(target: Any) -> list[int]:
    """The types the target holds"""
    return sorted(document[PUBLIC_ID] for document in target[CmdbType.COLLECTION].find({}, {PUBLIC_ID: 1}))


def _recorded(database_manager: MongoDatabaseManager, target: Any) -> dict[str, Any]:
    """The decision as the offer reads it"""
    return read_decision(SettingsManager(database_manager, target.name))


def test_the_model_is_imported_and_recorded(database_manager: MongoDatabaseManager, target: Any,
                                            model: BestPracticeModel) -> None:
    """Every type stored; best_practice_model with the model's id and the administrator"""
    apply_best_practice_models([model], ADMINISTRATOR)

    recorded = _recorded(database_manager, target)
    assert _type_ids(target) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]
    assert (recorded[StartAssistantKey.DECISION.value], recorded[StartAssistantKey.MODELS.value],
            recorded[StartAssistantKey.DECIDED_BY.value]) == (
                StartAssistantDecision.BEST_PRACTICE_MODEL.value, [MODEL_ID], ADMINISTRATOR.public_id)


@pytest.mark.usefixtures('target')
def test_the_cached_model_is_unchanged_by_the_import(model: BestPracticeModel) -> None:
    """The next request applies the same file"""
    loaded: dict[str, Any] = deepcopy(model.document)

    apply_best_practice_models([model], ADMINISTRATOR)

    assert model.document == loaded


def test_a_second_model_is_refused_and_the_first_decision_stays(database_manager: MongoDatabaseManager, target: Any,
                                                                model: BestPracticeModel) -> None:
    """The system is no longer reset: 400, nothing changed"""
    apply_best_practice_models([model], ADMINISTRATOR)
    first: dict[str, Any] = _recorded(database_manager, target)

    with pytest.raises(HTTPException) as exc_info:
        apply_best_practice_models([model], ADMINISTRATOR)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert _recorded(database_manager, target) == first
    assert _type_ids(target) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]


def _fail_the_relations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every relation insert fails - after the section templates and the types were written"""
    original = BaseManager.insert_many

    def _failing_on_relations(self: BaseManager, data: list[dict[str, Any]], skip_public: bool = False) -> list[int]:
        if self.collection == CmdbRelation.COLLECTION:
            raise RuntimeError('relations unavailable')

        return original(self, data, skip_public)

    monkeypatch.setattr(BaseManager, 'insert_many', _failing_on_relations)


def test_a_write_failing_half_way_is_undone_and_records_nothing(target: Any, model: BestPracticeModel,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """The relations fail after the types were written: the types are deleted again, no decision - the error passes
    through for the route's 500"""
    _fail_the_relations(monkeypatch)

    with pytest.raises(RuntimeError):
        apply_best_practice_models([model], ADMINISTRATOR)

    assert not _type_ids(target)
    assert target[SettingsManager.COLLECTION].find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None


def _both(tmp_path: Path, company_field_label: str | None = None) -> list[BestPracticeModel]:
    """The clients model and the suppliers model sharing its company, in card order"""
    write_model_file(tmp_path, MODEL_ID, document=model_document(with_supernet=False))
    second: dict[str, Any] = (second_model_document() if company_field_label is None
                              else second_model_document(company_field_label=company_field_label))
    write_model_file(tmp_path, SECOND_MODEL_ID, document=second, meta=second_model_meta())

    return list(load_catalogue(tmp_path).models)


def _field_targets(type_document: dict[str, Any], field_name: str) -> Any:
    """The ref_types of one stored field"""
    return next(field['ref_types'] for field in type_document['fields'] if field['name'] == field_name)


def test_two_models_are_stored_as_one(database_manager: MongoDatabaseManager, target: Any, tmp_path: Path) -> None:
    """The shared company once; both references meet it; one category holding every type; both relations"""
    apply_best_practice_models(_both(tmp_path), ADMINISTRATOR)

    types: dict[str, dict[str, Any]] = {document['name']: document for document in target[CmdbType.COLLECTION].find()}
    company_id: int = types[COMPANY_NAME][PUBLIC_ID]
    assert sorted(types) == sorted([COMPANY_NAME, CUSTOMER_NAME, SUPPLIER_NAME])
    assert _field_targets(types[CUSTOMER_NAME], EMPLOYER_FIELD) == [company_id]
    assert _field_targets(types[SUPPLIER_NAME], SUPPLIER_FIELD) == [company_id]
    category = target[CmdbCategory.COLLECTION].find_one({'name': CONTACT_NAME})
    assert category['types'] == [company_id, types[CUSTOMER_NAME][PUBLIC_ID], types[SUPPLIER_NAME][PUBLIC_ID]]
    supplies = target[CmdbRelation.COLLECTION].find_one({'relation_name': SUPPLIES_RELATION_NAME})
    assert (supplies['parent_type_ids'], supplies['child_type_ids']) == ([company_id],
                                                                         [types[SUPPLIER_NAME][PUBLIC_ID]])
    assert _recorded(database_manager, target)[StartAssistantKey.MODELS.value] == [MODEL_ID, SECOND_MODEL_ID]


def test_two_models_whose_shared_type_differs_write_nothing(target: Any, tmp_path: Path) -> None:
    """400 before the import; no type, no decision"""
    with pytest.raises(HTTPException) as exc_info:
        apply_best_practice_models(_both(tmp_path, company_field_label='Company name'), ADMINISTRATOR)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert not _type_ids(target)
    assert target[SettingsManager.COLLECTION].find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None


def test_two_models_failing_half_way_are_undone(target: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The combined import is one ledger: the relations fail, the types of both models are deleted again"""
    _fail_the_relations(monkeypatch)

    with pytest.raises(RuntimeError):
        apply_best_practice_models(_both(tmp_path), ADMINISTRATOR)

    assert not _type_ids(target)
    assert target[SettingsManager.COLLECTION].find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None


def _fail_the_decision(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> list[dict[str, Any]]:
    """
    Every write of the start assistant's section raises `failure`; other settings writes go through

    Returns:
        list[dict[str, Any]]: Filled with the configuration lock as stored at each failed write
    """
    original = SettingsManager.write
    locks_seen: list[dict[str, Any]] = []

    def _write(self: SettingsManager, _id: str, data: dict[str, Any]) -> Any:
        if _id == START_ASSISTANT_SETTINGS_SECTION and data.get(StartAssistantKey.DECISION.value) == \
                StartAssistantDecision.BEST_PRACTICE_MODEL.value:
            locks_seen.append(stored_configuration_lock(self.dbm, self.db_name))
            raise failure

        return original(self, _id, data)

    monkeypatch.setattr(SettingsManager, 'write', _write)

    return locks_seen


def test_a_failed_decision_undoes_the_import(target: Any, model: BestPracticeModel,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """The decision is part of the import: no type stays, no decision is stored - the error passes through for the
    route's 500"""
    failure = DocumentUpdateError('settings unavailable')
    _fail_the_decision(monkeypatch, failure)

    with pytest.raises(DocumentUpdateError) as raised:
        apply_best_practice_models([model], ADMINISTRATOR)

    assert raised.value is failure
    assert not _type_ids(target)
    assert target[SettingsManager.COLLECTION].find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None


def test_a_failed_decision_puts_an_earlier_decision_back(database_manager: MongoDatabaseManager, target: Any,
                                                         model: BestPracticeModel,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty data model chosen before stays recorded as it was"""
    earlier: dict[str, Any] = build_decision_document(StartAssistantDecision.EMPTY_DATA_MODEL, ADMINISTRATOR)
    SettingsManager(database_manager, target.name).write(START_ASSISTANT_SETTINGS_SECTION, earlier)
    stored_before: dict[str, Any] = _recorded(database_manager, target)
    _fail_the_decision(monkeypatch, DocumentUpdateError('settings unavailable'))

    with pytest.raises(DocumentUpdateError):
        apply_best_practice_models([model], ADMINISTRATOR)

    assert _recorded(database_manager, target) == stored_before
    assert not _type_ids(target)


def test_a_temporary_error_passes_through_and_a_retry_succeeds(database_manager: MongoDatabaseManager, target: Any,
                                                               model: BestPracticeModel,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's handlers answer it 503 - true now: nothing was applied, so the retry imports and records"""
    working_write = SettingsManager.write
    _fail_the_decision(monkeypatch, DocumentNetworkError('connection reset'))

    with pytest.raises(DocumentNetworkError):
        apply_best_practice_models([model], ADMINISTRATOR)

    monkeypatch.setattr(SettingsManager, 'write', working_write)
    apply_best_practice_models([model], ADMINISTRATOR)

    assert _type_ids(target) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]
    assert _recorded(database_manager, target)[StartAssistantKey.MODELS.value] == [MODEL_ID]


def test_the_decision_is_written_while_the_lock_is_held(database_manager: MongoDatabaseManager, target: Any,
                                                        model: BestPracticeModel,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """No reset can run between the import and the decision - and the lock is released after the failure"""
    locks_seen = _fail_the_decision(monkeypatch, DocumentUpdateError('settings unavailable'))

    with pytest.raises(DocumentUpdateError):
        apply_best_practice_models([model], ADMINISTRATOR)

    assert len(locks_seen) == 1 and locks_seen[0] is not None
    assert stored_configuration_lock(database_manager, target.name) is None
