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
Unit tests for cmdb.database.database_services.collection_validator

The MongoDatabaseManager, the per-domain managers and the key generator are all mocked, and the
FRAMEWORK_CLASSES / USER_MANAGEMENT_COLLECTION registries are monkeypatched to small controlled
lists so the create-or-reconcile branching, the predefined-data seeder dispatch and the index
reconciliation (including the symmetric user-management reconcile) can be asserted without a live
MongoDB. The full end-to-end bootstrap is covered by the integration / functional suites.
"""
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
from pymongo import IndexModel

from cmdb.database.database_constants import DG_CACHE_DB
from cmdb.database.database_services import collection_validator as cv_module
from cmdb.database.database_services.collection_validator import CollectionValidator

from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.cached_user_model.cmdb_cached_user import CmdbCachedUser
from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_management_constants import __FIXED_GROUPS__

from cmdb.errors.database import DocumentInsertError, DocumentUpdateError
from cmdb.errors.database.collection_validator import CollectionInitError, CollectionValidationError
# -------------------------------------------------------------------------------------------------------------------- #
# These unit tests deliberately exercise the validator's private seeders and index-reconcile helper
# pylint: disable=protected-access

MODULE: str = 'cmdb.database.database_services.collection_validator'
DB_NAME: str = 'test_db'
GENERAL_CATEGORY: dict[str, Any] = {'name': 'General', 'predefined': True}


class _FakeModel:
    """A minimal model stand-in with the surface CollectionValidator reads (COLLECTION, indexes)"""
    COLLECTION: str = 'fake_collection'

    @staticmethod
    def get_index_keys() -> list[IndexModel]:
        """Returns a single throwaway index model"""
        return [IndexModel([('field', 1)], name='fake_idx')]


@pytest.fixture(name='dbm')
def fixture_dbm() -> MagicMock:
    """A mocked MongoDatabaseManager"""
    return MagicMock()


@pytest.fixture(name='validator')
def fixture_validator(dbm: MagicMock) -> CollectionValidator:
    """A cloud-mode CollectionValidator backed by the mocked manager"""
    return CollectionValidator(DB_NAME, dbm, local_mode=False)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ensure_indexes                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_ensure_indexes_creates_only_missing(validator: CollectionValidator, dbm: MagicMock) -> None:
    """Only indexes whose name is not already present are created"""
    idx_a: IndexModel = IndexModel([('a', 1)], name='idx_a')
    idx_b: IndexModel = IndexModel([('b', 1)], name='idx_b')
    dbm.get_index_info.return_value = {'idx_a': {}}

    validator.ensure_indexes('coll', DB_NAME, [idx_a, idx_b])

    dbm.create_indexes.assert_called_once_with('coll', DB_NAME, [idx_b])


def test_ensure_indexes_noop_when_all_present(validator: CollectionValidator, dbm: MagicMock) -> None:
    """No index is created when every expected index already exists"""
    idx_a: IndexModel = IndexModel([('a', 1)], name='idx_a')
    dbm.get_index_info.return_value = {'idx_a': {}}

    validator.ensure_indexes('coll', DB_NAME, [idx_a])

    dbm.create_indexes.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                             validate_collections                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_validate_collections_runs_all_steps_in_order(validator: CollectionValidator) -> None:
    """The four init steps run once each, in the documented order"""
    calls: list[str] = []
    validator.init_database = MagicMock(side_effect=lambda: calls.append('database'))
    validator.init_framework_collections = MagicMock(side_effect=lambda: calls.append('framework'))
    validator.init_management_collections = MagicMock(side_effect=lambda: calls.append('management'))
    validator.init_cache_db = MagicMock(side_effect=lambda: calls.append('cache'))

    validator.validate_collections()

    assert calls == ['database', 'framework', 'management', 'cache']


def test_validate_collections_wraps_errors(validator: CollectionValidator) -> None:
    """A failure in any init step is wrapped in CollectionValidationError"""
    validator.init_database = MagicMock(side_effect=RuntimeError('boom'))
    validator.init_framework_collections = MagicMock()
    validator.init_management_collections = MagicMock()
    validator.init_cache_db = MagicMock()

    with pytest.raises(CollectionValidationError):
        validator.validate_collections()

# -------------------------------------------------------------------------------------------------------------------- #
#                                          init_database / init_keys                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_init_database_creates_and_seeds_keys_when_missing(validator: CollectionValidator, dbm: MagicMock) -> None:
    """A missing database is created and key generation is triggered"""
    dbm.check_database_exists.return_value = False
    validator.init_keys = MagicMock()

    validator.init_database()

    dbm.create_database.assert_called_once_with(DB_NAME)
    validator.init_keys.assert_called_once()


def test_init_database_noop_when_exists(validator: CollectionValidator, dbm: MagicMock) -> None:
    """An existing database is left untouched"""
    dbm.check_database_exists.return_value = True
    validator.init_keys = MagicMock()

    validator.init_database()

    dbm.create_database.assert_not_called()
    validator.init_keys.assert_not_called()


def test_init_keys_generates_in_local_mode(dbm: MagicMock) -> None:
    """Local mode generates the RSA keypair and the symmetric AES key"""
    validator: CollectionValidator = CollectionValidator(DB_NAME, dbm, local_mode=True)

    with patch(f'{MODULE}.KeyGenerator') as key_generator_cls:
        validator.init_keys()

        key_generator_cls.assert_called_once_with(dbm)
        key_generator_cls.return_value.generate_rsa_keypair.assert_called_once()
        key_generator_cls.return_value.generate_symmetric_aes_key.assert_called_once()


def test_init_keys_noop_in_cloud_mode(validator: CollectionValidator) -> None:
    """Cloud mode does not generate any keys"""
    with patch(f'{MODULE}.KeyGenerator') as key_generator_cls:
        validator.init_keys()

        key_generator_cls.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                               init_cache_db                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_init_cache_db_creates_when_missing(validator: CollectionValidator, dbm: MagicMock) -> None:
    """A missing cache database is created together with the cached-user collection and its indexes"""
    dbm.check_database_exists.return_value = False

    validator.init_cache_db()

    dbm.create_database.assert_called_once_with(DG_CACHE_DB)
    dbm.create_collection.assert_called_once_with(CmdbCachedUser.COLLECTION, DG_CACHE_DB)
    dbm.create_indexes.assert_called_once()


def test_init_cache_db_noop_when_exists(validator: CollectionValidator, dbm: MagicMock) -> None:
    """An existing cache database is left untouched"""
    dbm.check_database_exists.return_value = True

    validator.init_cache_db()

    dbm.create_database.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                              set_root_location                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_set_root_location_inits_counter_when_missing(validator: CollectionValidator, dbm: MagicMock) -> None:
    """On first creation with no counter present, the public_id counter is initialised"""
    dbm.get_collection.return_value.find_one.return_value = None

    validator.set_root_location('locations', DB_NAME, create=True)

    dbm.init_public_id_counter.assert_called_once_with('locations', DB_NAME)
    dbm.upsert_set.assert_called_once()


def test_set_root_location_skips_counter_when_present(validator: CollectionValidator, dbm: MagicMock) -> None:
    """On creation with an existing counter, the counter is not re-initialised"""
    dbm.get_collection.return_value.find_one.return_value = {'_id': 'locations'}

    validator.set_root_location('locations', DB_NAME, create=True)

    dbm.init_public_id_counter.assert_not_called()
    dbm.upsert_set.assert_called_once()


def test_set_root_location_update_skips_counter(validator: CollectionValidator, dbm: MagicMock) -> None:
    """The update path (create=False) never touches the counter"""
    validator.set_root_location('locations', DB_NAME, create=False)

    dbm.init_public_id_counter.assert_not_called()
    dbm.upsert_set.assert_called_once()


def test_set_root_location_wraps_errors(validator: CollectionValidator, dbm: MagicMock) -> None:
    """A failure during the upsert is wrapped in DocumentUpdateError"""
    dbm.get_collection.return_value.find_one.return_value = {'_id': 'locations'}
    dbm.upsert_set.side_effect = RuntimeError('boom')

    with pytest.raises(DocumentUpdateError):
        validator.set_root_location('locations', DB_NAME, create=True)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          init_predefined_templates                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_init_predefined_templates_inserts_only_missing(validator: CollectionValidator, dbm: MagicMock) -> None:
    """Only predefined templates whose name is not already stored are inserted"""
    collection: str = 'section_templates'

    def find_one(query: dict[str, Any]) -> dict[str, Any] | None:
        if query == {'_id': collection}:
            return {'_id': collection}
        if query == {'name': 'existing'}:
            return {'name': 'existing'}
        return None

    dbm.get_collection.return_value.find_one.side_effect = find_one

    with patch(f'{MODULE}.SectionTemplateCreator') as creator_cls:
        creator_cls.return_value.get_predefined_templates.return_value = [
            {'name': 'existing'},
            {'name': 'fresh'},
        ]

        validator.init_predefined_templates(collection, DB_NAME)

    dbm.insert.assert_called_once_with(collection, DB_NAME, {'name': 'fresh'})


def test_init_predefined_templates_wraps_errors(validator: CollectionValidator, dbm: MagicMock) -> None:
    """A failure while seeding templates is wrapped in DocumentInsertError"""
    dbm.get_collection.side_effect = RuntimeError('boom')

    with patch(f'{MODULE}.SectionTemplateCreator'):
        with pytest.raises(DocumentInsertError):
            validator.init_predefined_templates('section_templates', DB_NAME)

# -------------------------------------------------------------------------------------------------------------------- #
#                                        create_general_report_category                                              #
# -------------------------------------------------------------------------------------------------------------------- #

def test_create_general_report_category_inserts_when_missing(
    validator: CollectionValidator, dbm: MagicMock,
) -> None:
    """The 'General' category is inserted when it does not yet exist"""
    collection: str = 'report_categories'

    def find_one(query: dict[str, Any]) -> dict[str, Any] | None:
        if query == {'_id': collection}:
            return {'_id': collection}
        return None

    dbm.get_collection.return_value.find_one.side_effect = find_one

    validator.create_general_report_category(collection, DB_NAME)

    dbm.insert.assert_called_once_with(collection, DB_NAME, GENERAL_CATEGORY)


def test_create_general_report_category_skips_when_present(
    validator: CollectionValidator, dbm: MagicMock,
) -> None:
    """The 'General' category is left untouched when it already exists"""
    collection: str = 'report_categories'

    def find_one(query: dict[str, Any]) -> dict[str, Any] | None:
        if query == {'_id': collection}:
            return {'_id': collection}
        if query == {'name': 'General'}:
            return {'name': 'General'}
        return None

    dbm.get_collection.return_value.find_one.side_effect = find_one

    validator.create_general_report_category(collection, DB_NAME)

    dbm.insert.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                        _reconcile_collection_indexes                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_reconcile_collection_indexes_delegates_to_ensure(validator: CollectionValidator) -> None:
    """Reconciliation delegates to ensure_indexes with the collection and expected indexes"""
    validator.ensure_indexes = MagicMock()
    expected: list[IndexModel] = _FakeModel.get_index_keys()

    validator._reconcile_collection_indexes(_FakeModel, expected)

    validator.ensure_indexes.assert_called_once_with(_FakeModel.COLLECTION, DB_NAME, expected)


def test_reconcile_collection_indexes_swallows_errors(validator: CollectionValidator) -> None:
    """An index failure is logged and swallowed, never aborting the pass"""
    validator.ensure_indexes = MagicMock(side_effect=RuntimeError('boom'))

    # Must not raise
    validator._reconcile_collection_indexes(_FakeModel, [])

# -------------------------------------------------------------------------------------------------------------------- #
#                                       framework predefined-data seeders                                            #
# -------------------------------------------------------------------------------------------------------------------- #

def test_seed_root_location_delegates(validator: CollectionValidator) -> None:
    """The root-location seeder calls set_root_location with create=True"""
    validator.set_root_location = MagicMock()

    validator._seed_root_location()

    validator.set_root_location.assert_called_once_with(CmdbLocation.COLLECTION, DB_NAME, create=True)


def test_seed_general_report_category_delegates(validator: CollectionValidator) -> None:
    """The report-category seeder calls create_general_report_category"""
    validator.create_general_report_category = MagicMock()

    validator._seed_general_report_category()

    validator.create_general_report_category.assert_called_once_with(CmdbReportCategory.COLLECTION, DB_NAME)


def test_seed_default_protection_goals_inserts_each(validator: CollectionValidator, dbm: MagicMock) -> None:
    """Every default protection goal is inserted"""
    with patch(f'{MODULE}.get_default_protection_goals', return_value=[{'g': 1}, {'g': 2}]):
        validator._seed_default_protection_goals()

    assert dbm.insert.call_count == 2


def test_seed_default_risk_matrix_upserts(validator: CollectionValidator, dbm: MagicMock) -> None:
    """The default risk matrix is upserted once"""
    with patch(f'{MODULE}.get_default_risk_matrix', return_value={'matrix': 1}):
        validator._seed_default_risk_matrix()

    dbm.upsert_set.assert_called_once()


def test_seed_predefined_extendable_options_inserts_each(validator: CollectionValidator, dbm: MagicMock) -> None:
    """Every predefined extendable option of every feature is inserted"""
    with patch(f'{MODULE}.get_default_isms_extendable_options', return_value=[{'o': 1}]), \
         patch(f'{MODULE}.get_default_port_extendable_options', return_value=[{'o': 2}, {'o': 3}]):
        validator._seed_predefined_extendable_options()

    assert dbm.insert.call_count == 3


def test_seed_predefined_extendable_options_covers_every_feature(
    validator: CollectionValidator, dbm: MagicMock,
) -> None:
    """
    Both feature sources reach the collection, not just the first.

    The seeder grew a second source when Port Connectivity landed; a future third one being added to
    the import but not to the list would otherwise be silently dropped on every fresh install.
    """
    validator._seed_predefined_extendable_options()

    seeded = [call.args[2] for call in dbm.insert.call_args_list]
    option_types = {str(option['option_type']) for option in seeded}

    assert 'OptionType.IMPLEMENTATION_STATE' in option_types  # ISMS
    assert 'OptionType.PORT_STATUS' in option_types           # Port Connectivity
    assert 'OptionType.CABLE_TYPE' in option_types

# -------------------------------------------------------------------------------------------------------------------- #
#                                          init_framework_collections                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_init_framework_creates_missing_collection(
    validator: CollectionValidator, dbm: MagicMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A framework collection that does not exist is created with its indexes"""
    monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [_FakeModel])
    validator.get_all_db_collections = MagicMock(return_value=[])

    validator.init_framework_collections()

    dbm.create_collection.assert_called_once_with(_FakeModel.COLLECTION, DB_NAME)
    dbm.create_indexes.assert_called_once()


def test_init_framework_reconciles_existing_collection(
    validator: CollectionValidator, dbm: MagicMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing framework collection is reconciled, not recreated"""
    monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [_FakeModel])
    validator.get_all_db_collections = MagicMock(return_value=[_FakeModel.COLLECTION])
    validator._reconcile_collection_indexes = MagicMock()

    validator.init_framework_collections()

    dbm.create_collection.assert_not_called()
    validator._reconcile_collection_indexes.assert_called_once()


def test_init_framework_dispatches_seeder(
    validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creating a seeded framework collection routes to its predefined-data seeder"""
    monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [CmdbReportCategory])
    validator.get_all_db_collections = MagicMock(return_value=[])
    validator.create_general_report_category = MagicMock()

    validator.init_framework_collections()

    validator.create_general_report_category.assert_called_once()


def test_init_framework_seeds_section_templates_unconditionally(
    validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Predefined section templates are seeded even when their collection already exists"""
    monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [CmdbSectionTemplate])
    validator.get_all_db_collections = MagicMock(return_value=[CmdbSectionTemplate.COLLECTION])
    validator._reconcile_collection_indexes = MagicMock()
    validator.init_predefined_templates = MagicMock()

    validator.init_framework_collections()

    validator.init_predefined_templates.assert_called_once_with(CmdbSectionTemplate.COLLECTION, DB_NAME)


def test_init_framework_wraps_errors(
    validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure during the framework pass is wrapped in CollectionInitError"""
    monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [_FakeModel])
    validator.get_all_db_collections = MagicMock(side_effect=RuntimeError('boom'))

    with pytest.raises(CollectionInitError):
        validator.init_framework_collections()

# -------------------------------------------------------------------------------------------------------------------- #
#                                         init_management_collections                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_init_management_creates_missing_collection(
    validator: CollectionValidator, dbm: MagicMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-management collection that does not exist is created with its indexes"""
    monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [_FakeModel])
    validator.get_all_db_collections = MagicMock(return_value=[])

    validator.init_management_collections()

    dbm.create_collection.assert_called_once_with(_FakeModel.COLLECTION, DB_NAME)


def test_init_management_reconciles_existing_collection(
    validator: CollectionValidator, dbm: MagicMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing user-management collection is reconciled (the framework/management symmetry)"""
    monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [_FakeModel])
    validator.get_all_db_collections = MagicMock(return_value=[_FakeModel.COLLECTION])
    validator._reconcile_collection_indexes = MagicMock()

    validator.init_management_collections()

    dbm.create_collection.assert_not_called()
    validator._reconcile_collection_indexes.assert_called_once()
    assert validator._reconcile_collection_indexes.call_args.args[0] is _FakeModel


def test_init_management_seeds_fixed_groups(
    validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creating the user-group collection seeds every fixed group"""
    monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUserGroup])
    validator.get_all_db_collections = MagicMock(return_value=[])

    with patch(f'{MODULE}.GroupsManager') as groups_manager_cls:
        validator.init_management_collections()

        assert groups_manager_cls.return_value.insert_group.call_count == len(__FIXED_GROUPS__)


def test_init_management_creates_admin_user_in_local_mode(
    dbm: MagicMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In local mode the default admin user is created"""
    validator: CollectionValidator = CollectionValidator(DB_NAME, dbm, local_mode=True)
    monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUser])
    validator.get_all_db_collections = MagicMock(return_value=[])

    with patch(f'{MODULE}.SecurityManager'), patch(f'{MODULE}.UsersManager') as users_manager_cls:
        validator.init_management_collections()

        users_manager_cls.return_value.insert_user.assert_called_once()


def test_init_management_skips_admin_user_in_cloud_mode(
    validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In cloud mode the default admin user is not created"""
    monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUser])
    validator.get_all_db_collections = MagicMock(return_value=[])

    with patch(f'{MODULE}.SecurityManager'), patch(f'{MODULE}.UsersManager') as users_manager_cls:
        validator.init_management_collections()

        users_manager_cls.return_value.insert_user.assert_not_called()
