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
The bundled best-practice models, applied for real - every model that ships has to pass here

For each pair in ``configuration_transfer/best_practice_models`` (the folder the binary bundles): the model is applied
by the real apply step (``apply_best_practice_models``) into a scratch target that records the **newest** database
version - what a freshly started installation records, so a model exported from an older release is migrated by the
real updaters exactly as in production - licensed for every feature, as the full model. Afterwards the categories,
types, fields and relations stored equal the preview's counts, which is what the assistant showed. The same check runs
on the test fixture model, so the check itself is proven while the folder ships no model yet. **Every bundled model
applied together** passes it too: two bundles whose entries of one name differ cannot be selected together, so they
fail here before they ship - being identical carries over, so if all of them combine, every selection of them does. The
two fixture models prove that check, each migrated by the real updaters before they are combined. The ``example/`` pair
the folder's README points to passes the same check - so the example stays a valid model as the format evolves - and is
never offered: the catalogue reads the folder's own files only. And the ``Makefile``'s binary target bundles the
folder - without it the binary would offer nothing
"""
import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.framework.configuration_transfer import (
    BestPracticeModel,
    build_model_preview,
    combine_models,
    find_preview_problems,
    get_best_practice_catalogue,
    load_catalogue,
)
from cmdb.framework.configuration_transfer.best_practice_catalogue import default_models_folder
from cmdb.manager import SettingsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.category_model import CmdbCategory
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper import apply_best_practice_models
from tests.utils.best_practice_model_fixture import (
    second_model_document,
    second_model_meta,
    write_model_file,
)
# -------------------------------------------------------------------------------------------------------------------- #

pytestmark = pytest.mark.usefixtures('rest_api_app_context')

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
MAKEFILE: Path = REPO_ROOT / 'Makefile'
TARGET_SUFFIX: str = '-best-practice-bundle-target'
FIXTURE_MODEL_ID: str = 'fixture'
SECOND_FIXTURE_MODEL_ID: str = 'fixture_second'
EXAMPLE_FOLDER: Path = default_models_folder() / 'example'
EXAMPLE_MODEL_ID: str = 'example_contacts'
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_id=ADMIN_GROUP_ID)
BUNDLED_IDS: list[str] = [model.model_id for model in get_best_practice_catalogue().models]


@pytest.fixture(name='target')
def fixture_target(database_manager: MongoDatabaseManager, database_name: str,
                   monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """
    A reset target at the newest database version, holding the groups; every feature licensed; the managers routed to
    it
    """
    name: str = f'{database_name}{TARGET_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)
    client[name][CmdbUserGroup.COLLECTION].insert_many(list(client[database_name][CmdbUserGroup.COLLECTION].find()))
    newest: int = DatabaseUpdater(database_manager, name).get_highest_update_version()
    SettingsManager(database_manager, name).write(UpdaterSetting.SECTION.value, {UpdaterSetting.VERSION.value: newest})
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: name))
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)

    yield client[name]

    client.drop_database(name)


def assert_models_apply_as_previewed(models: list[BestPracticeModel], target: Any) -> None:
    """
    Applies models together and compares what is stored with the counts of their combination's preview

    Args:
        models (list[BestPracticeModel]): The models, in card order
        target (Any): The scratch target's database handle
    """
    model_ids: list[str] = [model.model_id for model in models]
    for model in models:
        assert not find_preview_problems(model.document, model.meta), model.model_id
    combined = combine_models(models)
    assert not combined.conflicts, model_ids
    counts = build_model_preview(combined.document, combined.meta).counts

    apply_best_practice_models(models, ADMINISTRATOR)

    types: list[dict[str, Any]] = list(target[CmdbType.COLLECTION].find())
    assert len(types) == counts.types, model_ids
    assert sum(len(type_doc.get(TypeSchemaKey.FIELDS.value) or []) for type_doc in types) == counts.fields
    assert target[CmdbCategory.COLLECTION].count_documents({}) == counts.categories, model_ids
    assert target[CmdbRelation.COLLECTION].count_documents({}) == counts.relations, model_ids


@pytest.mark.parametrize('model_id', BUNDLED_IDS)
def test_every_bundled_model_applies_as_previewed(target: Any, model_id: str) -> None:
    """A bundle the import refuses, or one whose preview promises what it does not create, fails here"""
    assert_models_apply_as_previewed([get_best_practice_catalogue().get(model_id)], target)


def test_the_check_itself_holds_on_the_fixture_model(target: Any, tmp_path: Path) -> None:
    """Proven on a model that ships with the tests, while the folder ships none"""
    write_model_file(tmp_path, FIXTURE_MODEL_ID)

    assert_models_apply_as_previewed([load_catalogue(tmp_path).get(FIXTURE_MODEL_ID)], target)


@pytest.mark.skipif(len(BUNDLED_IDS) < 2, reason='fewer than two bundled models - nothing to combine')
def test_every_bundled_model_applies_together(target: Any) -> None:
    """Two bundles whose entries of one name differ fail here, before a user can select them together"""
    assert_models_apply_as_previewed(list(get_best_practice_catalogue().models), target)


def test_the_combined_check_holds_on_the_fixture_models(target: Any, tmp_path: Path) -> None:
    """Proven on two models sharing a type - each migrated to the newest version first, then combined"""
    write_model_file(tmp_path, FIXTURE_MODEL_ID)
    write_model_file(tmp_path, SECOND_FIXTURE_MODEL_ID, document=second_model_document(), meta=second_model_meta())

    assert_models_apply_as_previewed(list(load_catalogue(tmp_path).models), target)


def test_the_example_is_a_valid_model(target: Any) -> None:
    """The README's example loads, resolves and applies as previewed"""
    example: BestPracticeModel | None = load_catalogue(EXAMPLE_FOLDER).get(EXAMPLE_MODEL_ID)

    assert example is not None
    assert_models_apply_as_previewed([example], target)


def test_the_example_is_never_offered() -> None:
    """It sits in a subfolder, and the catalogue reads only the folder's own files"""
    assert EXAMPLE_MODEL_ID not in BUNDLED_IDS


def test_the_binary_bundles_the_models_folder() -> None:
    """The Makefile's PyInstaller call adds the folder under its own relative path"""
    folder: str = default_models_folder().relative_to(REPO_ROOT).as_posix()

    assert re.search(rf'--add-data\s+{re.escape(folder)}:{re.escape(folder)}\b', MAKEFILE.read_text(encoding='utf-8'))
