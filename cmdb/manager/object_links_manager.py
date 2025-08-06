# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This module contains the implementation of the ObjectLinksManager
"""
import logging
from datetime import datetime, timezone

from cmdb.database import MongoDatabaseManager

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_link_model import CmdbObjectLink
from cmdb.models.object_model import CmdbObject
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerIterationError,
    BaseManagerGetError,
    BaseManagerInsertError,
    BaseManagerDeleteError,
)
from cmdb.errors.manager.object_links_manager import (
    ObjectLinksManagerInsertError,
    ObjectLinksManagerGetError,
    ObjectLinksManagerGetObjectError,
    ObjectLinksManagerIterationError,
    ObjectLinksManagerDeleteError,
)
from cmdb.errors.models.cmdb_object_link import (
    CmdbObjectLinkToJsonError,
    CmdbObjectLinkInitFromDataError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ObjectLinksManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectLinksManager(BaseManager):
    """
    The ObjectLinksManager handles the interaction between the CmdbObjectLinks-API and the database

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        """
        Set the database connection and the queue for sending events

        Args:
            dbm (MongoDatabaseManager): Active database managers instance
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE
        """
        super().__init__(CmdbObjectLink.COLLECTION, dbm, database)


# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_object_link(self, link: dict | CmdbObjectLink) -> int:
        """
        Insert a single CmdbObjectLink into the database

        Args:
            link (dict | CmdbObjectLink): Data of the CmdbObjectLink as object or dictionary

        Raises:
            ObjectLinksManagerInsertError: If the CmdbObjectLink could not be inserted in the database
            ObjectLinksManagerGetObjectError: If one of the objects which should be linked can not be retrieved

        Returns:
            int: The public_id of the new inserted object link
        """
        try:
            if isinstance(link, CmdbObjectLink):
                link = CmdbObjectLink.to_json(link)

            if 'creation_time' not in link:
                link['creation_time'] = datetime.now(timezone.utc)

            # Verify both objects exist
            primary_object = self.get_one_from_other_collection(CmdbObject.COLLECTION, link['primary'])
            secondary_object = self.get_one_from_other_collection(CmdbObject.COLLECTION, link['secondary'])

            if not primary_object:
                raise ObjectLinksManagerGetObjectError(f"Object with ID: {link['primary']} not found!")
            if not secondary_object:
                raise ObjectLinksManagerGetObjectError(f"Object with ID: {link['secondary']} not found!")

            new_link_public_id = self.insert(link)

            return new_link_public_id
        except (BaseManagerInsertError, CmdbObjectLinkToJsonError) as err:
            raise ObjectLinksManagerInsertError(err) from err
        except BaseManagerGetError as err:
            raise ObjectLinksManagerInsertError(err) from err
        except ObjectLinksManagerGetObjectError as err:
            raise err
        except Exception as err:
            LOGGER.error("[insert_object_link] Exception: %s. Type: %s", err, type(err))
            raise ObjectLinksManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate(
            self,
            builder_params: BuilderParameters,
            user: CmdbUser = None,
            permission: AccessControlPermission = None) -> IterationResult[CmdbObjectLink]:
        """
        Iterates over CmdbObjectLinks

        Args:
            builder_params (BuilderParameters): Iteration conditions
            user (CmdbUser): User requesting this operation
            permission (AccessControlPermission): Required permission for this operation

        Raises:
            ObjectLinksManagerIterationError: When an error occured during iteration

        Returns:
            IterationResult[CmdbObjectLink]: All CmdbObjectLinks matching the builder_params
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)


            iteration_result: IterationResult[CmdbObjectLink] = IterationResult(aggregation_result,
                                                                                total,
                                                                                CmdbObjectLink)
            return iteration_result
        except BaseManagerIterationError as err:
            raise ObjectLinksManagerIterationError(err) from err
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise ObjectLinksManagerIterationError(err) from err


    def get_object_link(self, public_id: int) -> CmdbObjectLink | None:
        """
        Retrieve a single CmdbObjectLink by its public_id

        Args:
            public_id (int): public_id of the CmdbObjectLink

        Raises:
            ObjectLinksManagerGetError: When the CmdbObjectLink could not be retrieved

        Returns:
            CmdbObjectLink | None: The requested CmdbObjectLink if it exists
        """
        try:
            link_instance = self.get_one(public_id)

            if link_instance:
                link_instance = CmdbObjectLink.from_data(link_instance)

            return link_instance
        except CmdbObjectLinkInitFromDataError as err:
            raise ObjectLinksManagerGetError(err) from err
        except BaseManagerGetError as err:
            raise ObjectLinksManagerGetError(err) from err


    def check_link_exists(self, criteria: dict) -> bool:
        """
        Checks if a CmdbObjectLink exists with given primary and secondary public_id of CmdbObjects

        Args:
            criteria (dict): Dict with primary and secondary public_id's

        Raises:
            ObjectLinksManagerGetError: If retrieving the link fails
        Returns:
            bool: True if CmdbObjectLink exists, else False
        """
        try:
            link_instance = self.get_one_by(criteria)

            return bool(link_instance)
        except BaseManagerGetError as err:
            raise ObjectLinksManagerGetError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_object_link(self, public_id: int) -> bool:
        """
        Deletes a CmdbObjectLink with the given public_id

        Args:
            public_id (int): public_id of the CmdbObjectLink

        Raises:
            ObjectLinksManagerDeleteError: When the CmdbObjectlink could not be deleted or is not found

        Returns:
            CmdbObjectLink: The retrieved instance of the CmdbObjectLink before it was deleted
        """
        try:
            return self.delete({'public_id':public_id})
        except (BaseManagerGetError, BaseManagerDeleteError) as err:
            raise ObjectLinksManagerDeleteError(err) from err
