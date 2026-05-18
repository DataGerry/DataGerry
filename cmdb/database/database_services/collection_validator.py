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
First-boot bootstrap for a DataGerry tenant database

CollectionValidator is invoked once per database (once per process start in local mode, once
per tenant in cloud mode) to guarantee that every required collection exists, has its expected
indexes, and is seeded with the predefined data the application relies on: the root location,
the default ISMS protection goals, the default risk matrix, the predefined ISMS extendable
options, the predefined section templates, the General report category, the fixed user groups,
and in local mode the admin/admin user plus the AES/RSA keypair. Existing collections are
never re-seeded; only their indexes are reconciled against the current model definitions. The
shared cache database (DG_CACHE_DB) is created on the same pass when it is missing
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from pymongo import IndexModel
from pymongo.results import UpdateResult

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION, DG_CACHE_DB
from cmdb.database.predefined_data.isms_data import (
    get_default_protection_goals,
    get_default_risk_matrix,
    get_default_isms_extendable_options,
)
from cmdb.database.predefined_data.cmdb_data import get_root_location_data

from cmdb.manager import (
    GroupsManager,
    UsersManager,
    SecurityManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.cached_user_model.cmdb_cached_user import CmdbCachedUser

from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.isms_model import (
    IsmsProtectionGoal,
    IsmsRiskMatrix,
)
from cmdb.models.user_management_constants import (
    __FIXED_GROUPS__,
    __COLLECTIONS__ as USER_MANAGEMENT_COLLECTION
)

from cmdb.framework.constants import __COLLECTIONS__ as FRAMEWORK_CLASSES
from cmdb.framework.section_templates.section_template_creator import SectionTemplateCreator

from cmdb.security.key.generator import KeyGenerator

from cmdb.errors.database.collection_validator import (
    CollectionValidatorInitError,
    CollectionInitError,
    CollectionValidationError,
)
from cmdb.errors.database import (
    DocumentInsertError,
    DocumentUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

class CollectionValidator:
    """
    Brings a DataGerry tenant database up to its required steady state on startup

    On a fresh database, creates every framework and user-management collection with its
    expected indexes and seeds the predefined data each collection needs. On an existing
    database, leaves stored data untouched and only reconciles indexes against the current
    model definitions. The shared cache database (DG_CACHE_DB) is created on first run, and in
    local mode the admin/admin user and the AES/RSA keypair are generated as well
    """

    def __init__(self, db_name: str, dbm: MongoDatabaseManager, local_mode: bool = False) -> None:
        """
        Initialises the CollectionValidator with the target database and DB manager

        Args:
            db_name (str): Name of the tenant database whose collections should be validated
            dbm (MongoDatabaseManager): The database operations manager for MongoDB
            local_mode (bool): True when DataGerry runs in local (non-cloud) mode; gates the
                generation of encryption keys and the default admin user

        Raises:
            CollectionValidatorInitError: If the CollectionValidator could not be initialised
        """
        try:
            self.db_name = db_name
            self.dbm = dbm
            self.local_mode = local_mode
        except Exception as err:
            raise CollectionValidatorInitError(str(err)) from err


    def validate_collections(self) -> None:
        """
        Runs the full bootstrap pass for the configured tenant database

        Executes the four init steps in order: ensure the tenant database itself exists (and
        seed encryption keys in local mode), create / reconcile framework collections, create
        / reconcile user-management collections, and ensure the shared cache database. Any
        failure raised by an init step is wrapped in CollectionValidationError so callers see
        a single error type for boot-time validation issues

        Raises:
            CollectionValidationError: If any of the underlying init steps fails
        """
        try:
            LOGGER.info("Validating Collections for Database: %s!", self.db_name)
            self.init_database()
            self.init_framework_collections()
            self.init_management_collections()
            self.init_cache_db()
        except Exception as err:
            LOGGER.error("[validate_collections] Exception: %s. Type: %s.", err, type(err), exc_info=True)
            raise CollectionValidationError(str(err)) from err


    def init_database(self) -> None:
        """
        Creates the tenant database if it does not yet exist and seeds keys in local mode

        Skips entirely when the database already exists; the call is therefore idempotent and
        safe to invoke on every boot. Key generation is delegated to init_keys and only runs
        the first time the database is created (and only in local mode)
        """
        if not self.dbm.check_database_exists(self.db_name):
            self.dbm.create_database(self.db_name)
            self.init_keys()


    def init_cache_db(self) -> None:
        """
        Creates the shared DataGerry cache database on first boot

        DG_CACHE_DB hosts cross-tenant caches (currently the cached-user collection used by
        token validation). When the cache database is missing it is created together with the
        CmdbCachedUser collection and its indexes; when it already exists this method is a
        no-op (it does not reconcile the cache collection or its indexes)
        """
        if not self.dbm.check_database_exists(DG_CACHE_DB):
            self.dbm.create_database(DG_CACHE_DB)
            self.dbm.create_collection(CmdbCachedUser.COLLECTION, DG_CACHE_DB)
            self.dbm.create_indexes(CmdbCachedUser.COLLECTION, DG_CACHE_DB, CmdbCachedUser.get_index_keys())


    def init_keys(self) -> None:
        """
        Generates the RSA keypair and the symmetric AES key for a fresh local-mode database

        No-op in cloud mode: cloud-mode keys are provisioned outside the CollectionValidator
        flow. Invoked exactly once, from init_database, right after the tenant database has
        been created
        """
        if self.local_mode:
            kg = KeyGenerator(self.dbm)
            kg.generate_rsa_keypair()
            kg.generate_symmetric_aes_key()


    def init_framework_collections(self) -> None:
        """
        Creates or reconciles every framework collection declared in FRAMEWORK_CLASSES

        For each framework class:
          - If its collection does not yet exist, the collection is created with its expected
            indexes and the class-specific predefined data is seeded (the root CmdbLocation,
            the General report category, the default IsmsProtectionGoals, the default
            IsmsRiskMatrix, and the predefined ISMS CmdbExtendableOptions).
          - If the collection already exists, only the indexes are reconciled via
            ensure_indexes; per-collection index failures are logged but do not abort the
            overall pass.
        The predefined CmdbSectionTemplate seeding runs unconditionally on every pass (not
        gated by the create-vs-exists branch), so newly added predefined templates are picked
        up by existing deployments

        Raises:
            CollectionInitError: If any collection failed to be created or seeded
        """
        try:
            all_collections = self.get_all_db_collections(self.db_name)

            # Check all Framework Classes
            for framework_class in FRAMEWORK_CLASSES:
                # get the expected indexes
                expected_indexes = framework_class.get_index_keys()

                # If collection does not exist, create it and initialise with default data
                if framework_class.COLLECTION not in all_collections:
                    self.dbm.create_collection(framework_class.COLLECTION, self.db_name)
                    self.dbm.create_indexes(framework_class.COLLECTION, self.db_name, expected_indexes)

                    # Create the root CmdbLocation
                    if framework_class == CmdbLocation:
                        self.set_root_location(CmdbLocation.COLLECTION, self.db_name, create=True)

                    # Create the predefined CmdbReportCategories
                    if framework_class == CmdbReportCategory:
                        self.create_general_report_category(CmdbReportCategory.COLLECTION, self.db_name)

                    # Create the default IsmsProtectionGoals
                    if framework_class == IsmsProtectionGoal:
                        default_protection_goals = get_default_protection_goals()

                        for protection_goal in default_protection_goals:
                            self.dbm.insert(IsmsProtectionGoal.COLLECTION, self.db_name, protection_goal)

                    # Create the default IsmsRiskMatrix
                    if framework_class == IsmsRiskMatrix:
                        self.dbm.upsert_set(IsmsRiskMatrix.COLLECTION, self.db_name, get_default_risk_matrix())

                    # Create predefined CmdbExtendableOptions
                    if framework_class == CmdbExtendableOption:
                        predefined_isms_options = get_default_isms_extendable_options()

                        for predefined_isms_option in predefined_isms_options:
                            self.dbm.insert(CmdbExtendableOption.COLLECTION, self.db_name, predefined_isms_option)
                else:
                    try:
                        self.ensure_indexes(framework_class.COLLECTION, self.db_name, expected_indexes)
                    except Exception as err:
                        LOGGER.error(
                            "[init_framework_collections] Failed to update indexes for collection %s. "
                            "Exception: %s. Type: %s.",
                            framework_class.COLLECTION,
                            err,
                            type(err),
                            exc_info=True
                        )

                # Create the predefined CmdbSectionTemplates
                if framework_class == CmdbSectionTemplate:
                    self.init_predefined_templates(CmdbSectionTemplate.COLLECTION, self.db_name)
        except Exception as err:
            LOGGER.error("[init_framework_collections] Exception: %s. Type: %s.", err, type(err), exc_info=True)
            raise CollectionInitError(str(err)) from err


    def init_management_collections(self) -> None:
        """
        Creates or reconciles every user-management collection declared in USER_MANAGEMENT_COLLECTION

        For each management class:
          - If its collection does not yet exist, the collection is created with its expected
            indexes. The CmdbUserGroup collection is then seeded with the fixed user groups
            (admin, user, etc.) defined in __FIXED_GROUPS__. The CmdbUser collection is seeded
            with the default admin/admin user only in local mode; in cloud mode the initial
            user is provisioned elsewhere.
          - If the collection already exists, this method does NOT reconcile its indexes (in
            contrast to init_framework_collections, which does).

        Raises:
            CollectionInitError: If any collection failed to be created or seeded
        """
        try:
            all_collections: list[str] = self.get_all_db_collections(self.db_name)

            for management_class in USER_MANAGEMENT_COLLECTION:
                if management_class.COLLECTION not in all_collections:
                    self.dbm.create_collection(management_class.COLLECTION, self.db_name)
                    self.dbm.create_indexes(
                                    management_class.COLLECTION,
                                    self.db_name,
                                    management_class.get_index_keys()
                            )

                    if management_class == CmdbUserGroup:
                        groups_manager = GroupsManager(self.dbm, self.db_name)

                        for group in __FIXED_GROUPS__:
                            groups_manager.insert_group(group)

                    # The default admin CmdbUser is only created in local_mode
                    if management_class == CmdbUser and self.local_mode:
                        scm = SecurityManager(self.dbm, self.db_name)
                        users_manager = UsersManager(self.dbm, self.db_name)

                        # setting the initial user to admin/admin as default
                        admin_user = CmdbUser(
                            public_id=1,
                            user_name='admin',
                            active=True,
                            group_id=1,
                            registration_time=datetime.now(timezone.utc),
                            password=scm.generate_hmac('admin'),
                        )

                        users_manager.insert_user(admin_user)
        except Exception as err:
            LOGGER.error("[init_management_collections] Exception: %s. Type: %s.", err, type(err), exc_info=True)
            raise CollectionInitError(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_all_db_collections(self, db_name: str) -> list[str]:
        """
        Lists every collection name present in the given database

        Args:
            db_name (str): Name of the database to inspect

        Returns:
            list[str]: All collection names; empty list when the database has no collections
        """
        return self.dbm.connector.get_database(db_name).list_collection_names()


    def ensure_indexes(self, collection: str, db_name: str, expected: list[IndexModel]) -> None:
        """
        Adds any expected indexes that are missing on a collection, leaving existing ones intact

        Reads the collection's current index info, computes the subset of 'expected' indexes
        whose name is not already present, and creates only those. Existing indexes are not
        modified, dropped, or compared field-by-field — this is purely additive

        Args:
            collection (str): Name of the collection to reconcile
            db_name (str): Name of the database that owns the collection
            expected (list[IndexModel]): Index models the model class currently declares
        """
        existing_indexes = self.dbm.get_index_info(collection, db_name)

        existing_names = set(existing_indexes.keys())

        missing_indexes = []

        for index in expected:
            if index.document['name'] not in existing_names:
                missing_indexes.append(index)

        if missing_indexes:
            LOGGER.info("Updating Indexes for collections in database: %s!", db_name)
            self.dbm.create_indexes(collection, db_name, missing_indexes)

# ---------------------------------------------- CmdbLocation - SECTION ---------------------------------------------- #

    def set_root_location(self, collection: str, db_name: str, create: bool = False) -> UpdateResult:
        """
        Upserts the root CmdbLocation document and ensures its public_id counter exists

        Initialises the public_id counter for the collection on first creation (when 'create'
        is True and no counter is present yet), then upserts the root location document from
        get_root_location_data(). The 'create' flag currently affects only logging and the
        counter-init branch — the document write itself is the same upsert in both branches

        Args:
            collection (str): Name of the framework.locations collection
            db_name (str): Name of the database that owns the collection
            create (bool): True on first-time setup (also initialises the public_id counter);
                False when updating an existing root location

        Raises:
            DocumentUpdateError: If the public_id counter init or the upsert fails

        Returns:
            UpdateResult: The pymongo result of the upsert operation
        """
        try:
            # If creation is requested, ensure the counter exists
            if create:
                # Check if the counter exists, if not initialize it
                if not self.dbm.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).find_one({'_id': collection}):
                    self.dbm.init_public_id_counter(collection, db_name)

                # Insert root location data
                LOGGER.info("Creating ROOT location!")
                status = self.dbm.upsert_set(collection, self.db_name, get_root_location_data())
            else:
                # Update the root location data
                LOGGER.info("Updating ROOT location!")
                status = self.dbm.upsert_set(collection, self.db_name, get_root_location_data())

            return status
        except Exception as err:
            raise DocumentUpdateError(f"Error setting up root location for collection '{collection}': {err}") from err

# ------------------------------------------- CmdbSectionTemplate - Section ------------------------------------------ #

    def init_predefined_templates(self, collection: str, db_name: str) -> None:
        """
        Inserts any predefined CmdbSectionTemplates that are not yet present in the collection

        Ensures the public_id counter for the collection exists, then walks the predefined
        templates returned by SectionTemplateCreator and inserts each one whose 'name' is not
        already present in the collection. Existing templates with the same name are left
        untouched; this method does not overwrite or merge predefined content into them

        Args:
            collection (str): Name of the collection that stores section templates
            db_name (str): Name of the database that owns the collection

        Raises:
            DocumentInsertError: If counter init, the existence lookup, or any insert fails
        """
        try:
            counter = self.dbm.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).find_one({'_id': collection})

            if not counter:
                self.dbm.init_public_id_counter(collection, self.db_name)

            predefined_template_creator = SectionTemplateCreator()
            predefined_templates: list[dict] = predefined_template_creator.get_predefined_templates()

            for predefined_template in predefined_templates:
                # First, check if the template already exists
                template_name = predefined_template['name']
                result = self.dbm.get_collection(collection, self.db_name).find_one({'name': template_name})

                if not result:
                    # The template does not exist, create it
                    LOGGER.info("Creating Template: %s", template_name)
                    self.dbm.insert(collection, self.db_name, predefined_template)

        except Exception as err:
            raise DocumentInsertError(
                f"Error initializing predefined templates for collection '{collection}': {err}"
            ) from err

# ----------------------------------------------- CmdbReport - Section ----------------------------------------------- #

    def create_general_report_category(self, collection: str, db_name: str) -> None:
        """
        Inserts the predefined 'General' CmdbReportCategory if it is not already present

        Ensures the public_id counter for the collection exists, then looks up a category
        document whose 'name' is 'General' and inserts one when missing. The inserted document
        carries 'predefined: True' so the frontend can render it as system-owned and prevent
        deletion. Existing documents with the same name are left untouched

        Args:
            collection (str): Name of the collection that stores report categories
            db_name (str): Name of the database that owns the collection

        Raises:
            DocumentInsertError: If counter init, the existence lookup, or the insert fails
        """
        try:
            counter = self.dbm.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).find_one({'_id': collection})

            if not counter:
                self.dbm.init_public_id_counter(collection, db_name)

            result = self.dbm.get_collection(collection, db_name).find_one({'name': 'General'})

            if not result:
                # The category does not exist, create it
                LOGGER.info("Creating 'General' Report Category")

                general_category: dict[str, Any] = {
                    'name': 'General',
                    'predefined': True,
                }

                self.dbm.insert(collection, db_name, general_category)
        except Exception as err:
            LOGGER.error("[create_general_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
            raise DocumentInsertError(
                f"Unexpected error while creating 'General' report category for collection '{collection}': {err}"
            ) from err
