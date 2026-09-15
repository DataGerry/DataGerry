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
    """
    A mocked MongoDatabaseManager whose collections read as empty

    The seeders look a document up before inserting it, so a default MagicMock - whose find_one
    returns a truthy mock - would read as "everything is already seeded" and every seeding assertion
    would pass vacuously.
    """
    dbm = MagicMock()
    dbm.get_collection.return_value.find_one.return_value = None

    return dbm


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
    validator.init_framework_collections = MagicMock(side_effect=lambda *_: calls.append('framework'))
    validator.init_management_collections = MagicMock(side_effect=lambda *_: calls.append('management'))
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
    with patch(f'{MODULE}.get_default_protection_goals',
               return_value=[{'public_id': 1}, {'public_id': 2}]):
        validator._seed_default_protection_goals()

    assert dbm.insert.call_count == 2


def test_seed_default_risk_matrix_upserts(validator: CollectionValidator, dbm: MagicMock) -> None:
    """The default risk matrix is upserted once"""
    with patch(f'{MODULE}.get_default_risk_matrix', return_value={'matrix': 1}):
        validator._seed_default_risk_matrix()

    dbm.upsert_set.assert_called_once()


def test_seed_predefined_extendable_options_inserts_each(validator: CollectionValidator, dbm: MagicMock) -> None:
    """Every predefined extendable option of every feature is inserted"""
    isms_option: dict[str, Any] = {'option_type': 'ISMS_ONE', 'value': 'a'}
    port_options: list[dict[str, Any]] = [
        {'option_type': 'PORT_ONE', 'value': 'b'}, {'option_type': 'PORT_TWO', 'value': 'c'},
    ]

    with patch(f'{MODULE}.get_default_isms_extendable_options', return_value=[isms_option]), \
         patch(f'{MODULE}.get_default_port_extendable_options', return_value=port_options):
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                     self-healing seeding (a half-finished first boot)                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheSeedersRunOnEveryPass:
    """
    'The collection exists' used to stand for 'it has been seeded', and the two are not the same

    A boot that created a collection and then failed while seeding it left the collection behind. On
    the next start the create branch was skipped, so the seeding never happened again - a database
    permanently without its root location, its protection goals or its admin group, and a boot that
    reported success.
    """

    def test_an_existing_collection_is_still_seeded(
        self, validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch, dbm: MagicMock,
    ) -> None:
        """The create branch is no longer what decides whether the predefined data is written."""
        monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [CmdbLocation])
        validator.get_all_db_collections = MagicMock(return_value=[CmdbLocation.COLLECTION])
        validator.init_predefined_templates = MagicMock()

        validator.init_framework_collections()

        dbm.create_collection.assert_not_called()
        dbm.upsert_set.assert_called_once()

    def test_a_missing_protection_goal_is_restored_and_the_others_are_not_duplicated(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """
        Each default is looked up by public_id, so a half-seeded collection is completed

        Which is the difference between "insert everything again" and "insert what is missing".
        """
        stored: dict[int, dict[str, Any]] = {1: {'public_id': 1}}
        dbm.get_collection.return_value.find_one.side_effect = (
            lambda criteria: stored.get(criteria['public_id'])
        )

        with patch(f'{MODULE}.get_default_protection_goals',
                   return_value=[{'public_id': 1}, {'public_id': 2}, {'public_id': 3}]):
            validator._seed_default_protection_goals()  # pylint: disable=protected-access

        inserted = [call.args[2]['public_id'] for call in dbm.insert.call_args_list]

        assert inserted == [2, 3]

    def test_a_fully_seeded_collection_is_left_alone(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """Running on every boot must cost writes only when something is actually missing."""
        dbm.get_collection.return_value.find_one.return_value = {'public_id': 1}

        with patch(f'{MODULE}.get_default_protection_goals', return_value=[{'public_id': 1}]):
            validator._seed_default_protection_goals()  # pylint: disable=protected-access

        dbm.insert.assert_not_called()

    def test_a_predefined_option_is_identified_by_its_type_and_value(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """
        Extendable options carry no fixed public_id - the counter assigns one

        So the pair that identifies them is (option_type, value), and that is what the lookup asks
        for.
        """
        with patch(f'{MODULE}.get_default_isms_extendable_options',
                   return_value=[{'option_type': 'A_TYPE', 'value': 'a value'}]), \
             patch(f'{MODULE}.get_default_port_extendable_options', return_value=[]):
            validator._seed_predefined_extendable_options()  # pylint: disable=protected-access

        dbm.get_collection.return_value.find_one.assert_called_once_with(
            {'option_type': 'A_TYPE', 'value': 'a value'},
        )

    def test_a_missing_fixed_group_is_restored(
        self, validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        A CmdbUser's group_id points at these by public_id

        A user referencing group 1 in a database that has no group 1 cannot be authorised at all, so
        a missing fixed group is worth restoring rather than leaving for an operator to find.
        """
        monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUserGroup])
        validator.get_all_db_collections = MagicMock(return_value=[CmdbUserGroup.COLLECTION])

        with patch(f'{MODULE}.GroupsManager') as groups_manager_cls:
            validator.init_management_collections()

        assert groups_manager_cls.return_value.insert_group.call_count == len(__FIXED_GROUPS__)

    def test_an_existing_fixed_group_is_not_reinserted(
        self, validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch, dbm: MagicMock,
    ) -> None:
        """The lookup is by public_id, so a database with its groups pays no writes."""
        monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUserGroup])
        validator.get_all_db_collections = MagicMock(return_value=[CmdbUserGroup.COLLECTION])
        dbm.get_collection.return_value.find_one.return_value = {'public_id': 1}

        with patch(f'{MODULE}.GroupsManager') as groups_manager_cls:
            validator.init_management_collections()

        groups_manager_cls.return_value.insert_group.assert_not_called()


class TestTheDefaultAdminUser:
    """Whose seeding rule is deliberately different from every other seeder's."""

    def test_it_is_created_when_the_database_has_no_users(
        self, dbm: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A database nobody can log into is worth healing, and that is what an empty collection is."""
        validator: CollectionValidator = CollectionValidator(DB_NAME, dbm, local_mode=True)
        monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUser])
        validator.get_all_db_collections = MagicMock(return_value=[CmdbUser.COLLECTION])

        with patch(f'{MODULE}.UsersManager') as users_manager_cls, patch(f'{MODULE}.SecurityManager'):
            validator.init_management_collections()

        users_manager_cls.return_value.insert_user.assert_called_once()

    def test_it_is_not_recreated_when_any_user_exists(
        self, dbm: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        The check is 'are there users', not 'is there a user named admin'

        An installation that replaced the default account must not have admin/admin reappear on the
        next boot - which a name-based check would do.
        """
        validator: CollectionValidator = CollectionValidator(DB_NAME, dbm, local_mode=True)
        monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUser])
        validator.get_all_db_collections = MagicMock(return_value=[CmdbUser.COLLECTION])
        dbm.get_collection.return_value.find_one.return_value = {'public_id': 42, 'user_name': 'someone'}

        with patch(f'{MODULE}.UsersManager') as users_manager_cls, patch(f'{MODULE}.SecurityManager'):
            validator.init_management_collections()

        users_manager_cls.return_value.insert_user.assert_not_called()

    def test_cloud_mode_never_creates_one(
        self, validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A cloud tenant's first user is provisioned through the service portal."""
        monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUser])
        validator.get_all_db_collections = MagicMock(return_value=[])

        with patch(f'{MODULE}.UsersManager') as users_manager_cls, patch(f'{MODULE}.SecurityManager'):
            validator.init_management_collections()

        users_manager_cls.return_value.insert_user.assert_not_called()


class TestTheCacheDatabase:
    """The one registered collection that used to be created and then never looked at again."""

    def test_an_existing_cache_database_has_its_indexes_reconciled(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """
        A new index on CmdbCachedUser used to reach a fresh installation only

        Every upgraded one kept the index set of the day its cache database was created, and the
        collection-registry guard counts CmdbCachedUser as registered, so nothing pointed at it.
        """
        dbm.check_database_exists.return_value = True
        dbm.get_index_info.return_value = {}

        validator.init_cache_db()

        dbm.create_indexes.assert_called_once()
        assert dbm.create_indexes.call_args.args[1] == DG_CACHE_DB

    def test_an_up_to_date_cache_database_is_left_alone(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """The reconcile is additive, so a boot with nothing to add writes nothing."""
        dbm.check_database_exists.return_value = True
        dbm.get_index_info.return_value = {
            index.document['name']: {} for index in CmdbCachedUser.get_index_keys()
        }

        validator.init_cache_db()

        dbm.create_indexes.assert_not_called()

    def test_a_failing_cache_reconcile_does_not_stop_the_boot(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """
        The same rule the tenant collections follow

        One collection's index problem must not take down a boot that is otherwise fine - the cache
        is a cache, and token validation refills it.
        """
        dbm.check_database_exists.return_value = True
        dbm.get_index_info.side_effect = RuntimeError('index read failed')

        validator.init_cache_db()

    def test_a_missing_cache_database_is_created_with_its_collection(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """The first-boot path, unchanged."""
        dbm.check_database_exists.return_value = False

        validator.init_cache_db()

        dbm.create_database.assert_called_once_with(DG_CACHE_DB)
        dbm.create_collection.assert_called_once_with(CmdbCachedUser.COLLECTION, DG_CACHE_DB)


class TestTheCollectionListing:
    """One round trip per boot, not one per init step."""

    def test_the_listing_is_taken_once_and_shared(self, validator: CollectionValidator) -> None:
        """
        Both init steps ask the same question of the same database

        In cloud mode that was two extra round trips per tenant on every start.
        """
        validator.get_all_db_collections = MagicMock(return_value=[])
        validator.init_database = MagicMock()
        validator.init_framework_collections = MagicMock()
        validator.init_management_collections = MagicMock()
        validator.init_cache_db = MagicMock()

        validator.validate_collections()

        validator.get_all_db_collections.assert_called_once_with(DB_NAME)

    def test_an_init_step_called_on_its_own_still_lists_for_itself(
        self, validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        The parameter is optional, so the two steps remain callable in isolation

        Which is what the integration suites and any future caller do.
        """
        monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [])
        validator.get_all_db_collections = MagicMock(return_value=[])
        validator.init_predefined_templates = MagicMock()

        validator.init_framework_collections()

        validator.get_all_db_collections.assert_called_once_with(DB_NAME)


class TestTheRootLocation:
    """The document the whole location tree hangs off."""

    def test_the_write_is_the_same_upsert_whether_or_not_the_counter_is_initialised(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """
        The 'create' flag used to select between two identical upserts

        It now selects only whether the public_id counter is initialised as well.
        """
        with patch(f'{MODULE}.get_root_location_data', return_value={'public_id': 1}):
            validator.set_root_location('coll', DB_NAME, create=False)
            validator.set_root_location('coll', DB_NAME, create=True)

        first_write, second_write = dbm.upsert_set.call_args_list

        assert first_write == second_write

    def test_the_upsert_honours_the_database_it_was_given(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """
        It took a db_name and then wrote to self.db_name on both paths

        Harmless while the only caller passes its own database, and wrong the moment one does not.
        """
        with patch(f'{MODULE}.get_root_location_data', return_value={'public_id': 1}):
            validator.set_root_location('coll', 'another-db')

        assert dbm.upsert_set.call_args.args[1] == 'another-db'


class TestTheRemainingErrorArms:
    """A boot failure has to say which step failed, and with which error type."""

    def test_a_failing_management_step_is_wrapped(
        self, validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        CollectionInitError is what validate_collections then reports on

        The wrapper now carries the original exception rather than a string of it, so a caller
        inspecting it still sees the pymongo error underneath.
        """
        monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUserGroup])
        validator.get_all_db_collections = MagicMock(side_effect=RuntimeError('listing failed'))

        with pytest.raises(CollectionInitError) as caught:
            validator.init_management_collections()

        assert isinstance(caught.value.__cause__, RuntimeError)

    def test_a_failing_report_category_insert_is_wrapped(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """The seeder reports a write it could not do rather than letting pymongo's error escape."""
        dbm.insert.side_effect = RuntimeError('insert failed')

        with pytest.raises(DocumentInsertError):
            validator.create_general_report_category('coll', DB_NAME)

    def test_an_existing_predefined_option_is_not_inserted_again(
        self, validator: CollectionValidator, dbm: MagicMock,
    ) -> None:
        """The skip side of the content check, which is what every boot after the first takes."""
        dbm.get_collection.return_value.find_one.return_value = {'option_type': 'A_TYPE', 'value': 'a'}

        with patch(f'{MODULE}.get_default_isms_extendable_options',
                   return_value=[{'option_type': 'A_TYPE', 'value': 'a'}]), \
             patch(f'{MODULE}.get_default_port_extendable_options', return_value=[]):
            validator._seed_predefined_extendable_options()  # pylint: disable=protected-access

        dbm.insert.assert_not_called()

    def test_the_management_step_reuses_a_listing_it_is_given(
        self, validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The shared listing reaches this step too, so it asks the server for nothing itself."""
        monkeypatch.setattr(cv_module, 'USER_MANAGEMENT_COLLECTION', [CmdbUserGroup])
        validator.get_all_db_collections = MagicMock()

        with patch(f'{MODULE}.GroupsManager'):
            validator.init_management_collections([CmdbUserGroup.COLLECTION])

        validator.get_all_db_collections.assert_not_called()


def test_the_framework_step_reuses_a_listing_it_is_given(
    validator: CollectionValidator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The other half of the shared listing

    validate_collections lists once and hands the same names to both steps; each still lists for
    itself when called alone, which is what the integration suites do.
    """
    monkeypatch.setattr(cv_module, 'FRAMEWORK_CLASSES', [])
    validator.get_all_db_collections = MagicMock()
    validator.init_predefined_templates = MagicMock()

    validator.init_framework_collections([])

    validator.get_all_db_collections.assert_not_called()
