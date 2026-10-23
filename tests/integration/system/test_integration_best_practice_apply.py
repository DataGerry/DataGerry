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
Integration tests for applying a best-practice model (``best_practice_helper.apply_best_practice_model``) against a
real MongoDB

The managers' tenant resolver is pointed at a scratch target holding only its database version and the groups; the
model is the best-practice fixture model, loaded by the real catalogue. Pinned: the model is imported and
``best_practice_model`` recorded with its id - read back as the offer reads it; the cached model is not changed by the
import; a second model is refused and the first decision stays; a write that fails half-way is undone and records
nothing
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
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper import apply_best_practice_model
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
    StartAssistantDecision,
    StartAssistantKey,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper import read_decision
from tests.utils.best_practice_model_fixture import (
    COMPANY_TYPE_ID,
    CUSTOMER_TYPE_ID,
    MODEL_DB_VERSION,
    model_document,
    write_model_file,
)
# -------------------------------------------------------------------------------------------------------------------- #

pytestmark = pytest.mark.usefixtures('rest_api_app_context')

TARGET_SUFFIX: str = '-best-practice-apply-target'
MODEL_ID: str = 'clients'
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
    apply_best_practice_model(model, ADMINISTRATOR)

    recorded = _recorded(database_manager, target)
    assert _type_ids(target) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]
    assert (recorded[StartAssistantKey.DECISION.value], recorded[StartAssistantKey.MODEL.value],
            recorded[StartAssistantKey.DECIDED_BY.value]) == (
                StartAssistantDecision.BEST_PRACTICE_MODEL.value, MODEL_ID, ADMINISTRATOR.public_id)


@pytest.mark.usefixtures('target')
def test_the_cached_model_is_unchanged_by_the_import(model: BestPracticeModel) -> None:
    """The next request applies the same file"""
    loaded: dict[str, Any] = deepcopy(model.document)

    apply_best_practice_model(model, ADMINISTRATOR)

    assert model.document == loaded


def test_a_second_model_is_refused_and_the_first_decision_stays(database_manager: MongoDatabaseManager, target: Any,
                                                                model: BestPracticeModel) -> None:
    """The system is no longer reset: 400, nothing changed"""
    apply_best_practice_model(model, ADMINISTRATOR)
    first: dict[str, Any] = _recorded(database_manager, target)

    with pytest.raises(HTTPException) as exc_info:
        apply_best_practice_model(model, ADMINISTRATOR)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert _recorded(database_manager, target) == first
    assert _type_ids(target) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]


def test_a_write_failing_half_way_is_undone_and_records_nothing(target: Any, model: BestPracticeModel,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """The relations fail after the types were written: the types are deleted again, no decision - the error passes
    through for the route's 500"""
    original = BaseManager.insert_many

    def _failing_on_relations(self: BaseManager, data: list[dict[str, Any]], skip_public: bool = False) -> list[int]:
        if self.collection == CmdbRelation.COLLECTION:
            raise RuntimeError('relations unavailable')

        return original(self, data, skip_public)

    monkeypatch.setattr(BaseManager, 'insert_many', _failing_on_relations)

    with pytest.raises(RuntimeError):
        apply_best_practice_model(model, ADMINISTRATOR)

    assert not _type_ids(target)
    assert target[SettingsManager.COLLECTION].find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None
