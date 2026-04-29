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
Implementation of CollectionValidator
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
    The CollectionValidator makes sure that all required Collections and inital data in the Collections is created
    """

    def __init__(self, db_name: str, dbm: MongoDatabaseManager, local_mode: bool = False) -> None:
        """
        Initialises the CollectionValidator

        Args:
            db_name (str): name of the databae for which the collections should be checked
            dbm (MongoDatabaseManager): The database operations manager for MongoDB
            local_mode (bool): Set this to true if DataGerry is not used in __CLOUD_MODE__

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
        Validates all required collections for DataGerry

        Raises:
            CollectionValidationError: If validation of collections fails
        """
        try:
            LOGGER.info("Valdating Collections for Database: %s!", self.db_name)
            self.init_database()
            self.init_framework_collections()
            self.init_management_collections()
            self.init_cache_db()
        except Exception as err:
            LOGGER.error("[validate_collections] Exception: %s. Type: %s.", err, type(err), exc_info=True)
            raise CollectionValidationError(str(err)) from err


    def init_database(self) -> None:
        """
        Initialises a database if it does not exist and sets Keys if local_mode
        """
        if not self.dbm.check_database_exists(self.db_name):
            self.dbm.create_database(self.db_name)
            self.init_keys()


    def init_cache_db(self) -> None:
        """
        Created the DataGerry cache database
        """
        if not self.dbm.check_database_exists(DG_CACHE_DB):
            self.dbm.create_database(DG_CACHE_DB)
            self.dbm.create_collection(CmdbCachedUser.COLLECTION, DG_CACHE_DB)
            self.dbm.create_indexes(CmdbCachedUser.COLLECTION, DG_CACHE_DB, CmdbCachedUser.get_index_keys())


    def init_keys(self) -> None:
        """
        Initialises AES and symmetric keys in the database for local DataGerry version
        """
        if self.local_mode:
            kg = KeyGenerator(self.dbm)
            kg.generate_rsa_keypair()
            kg.generate_symmetric_aes_key()


    def init_framework_collections(self) -> None:
        """
        Checks if all required Framework collections exist, else initialises them

        Raises:
            CollectionInitError: If the initialisation of a collection failed
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

                    # Create the predefined CmdbSectionTemplates
                    if framework_class == CmdbSectionTemplate:
                        self.init_predefined_templates(CmdbSectionTemplate.COLLECTION, self.db_name)

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
        except Exception as err:
            LOGGER.error("[init_framework_collections] Exception: %s. Type: %s.", err, type(err), exc_info=True)
            raise CollectionInitError(str(err)) from err


    def init_management_collections(self) -> None:
        """
        Checks if all required Management collections exist, else initialises them

        Raises:
            CollectionInitError: If the initialisation of a collection failed
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

# -------------------------------------------------- HELEPER METHODS ------------------------------------------------- #

    def get_all_db_collections(self, db_name: str) -> list[str]:
        """
        Retrieves all collection names in the current database

        Returns:
            list[str]: List of all collection names
        """
        return self.dbm.connector.get_database(db_name).list_collection_names()


    def ensure_indexes(self, collection: str, db_name: str, expected: list[IndexModel]) -> None:
        """
        TODO: document
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
        Set up the root location. If no counter for locations exists, it will be created

        Args:
            collection (str): The framework.locations collection
            create (bool): If true the root location will be created, else it will be updated

        Raises:
            DocumentUpdateError: If there is an error during the root location setup, including issues with the
                                 database operation or creation of the public ID counter
            
        Returns:
            status: status of location creation or update
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
        Checks if all predefined templates are created, else creates them.

        Args:
            collection (str): The name of the collection where templates are stored

        Raises:
            DocumentInsertError: If there is an error inserting predefined templates into the collection
            DocumentGetError: If there is an error fetching data from the collection, such as when checking
                              for existing templates or counters
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
                else:
                    raise ValueError(
                        f"Template with name {template_name} exists preventing creation of a required SectionTemplate!"
                    )
        except Exception as err:
            raise DocumentInsertError(
                f"Error initializing predefined templates for collection '{collection}': {err}"
            ) from err

# ----------------------------------------------- CmdbReport - Section ----------------------------------------------- #

    def create_general_report_category(self, collection: str, db_name: str) -> None:
        """
        Creates the General Report Category if it does not already exist

        Args:
            collection (str): The name of the collection where the general report category is stored

        Raises:
            DocumentInsertError: If there is an error inserting the general report category into the collection
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
