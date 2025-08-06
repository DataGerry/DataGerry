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
This module contains the implementation of the CategoriesManager
"""
import logging

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.manager_errors import BaseManagerDeleteError
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.docapi_templates_manager import (
    DocapiTemplatesManagerInsertError,
    DocapiTemplatesManagerGetError,
    DocapiTemplatesManagerIterationError,
    DocapiTemplatesManagerUpdateError,
    DocapiTemplatesManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 DocapiManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class DocapiTemplatesManager(BaseManager):
    """
    The DocapiTemplatesManager handles the interaction between the DocapiTemplates-API and the database
    `Extends`: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database:str = None):
        """
        Set the database connection for the DocapiTemplatesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE
        """
        super().__init__(DocapiTemplate.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_template(self, data: DocapiTemplate | dict) -> int:
        """
        Insert a new DocapiTemplate into the database

        Args:
            `data` (DocapiTemplate | dict): The data of the new DocapiTemplate

        Raises:
            `DocapiTemplatesManagerInsertError`: When the creation of DocapiTemplate failed

        Returns:
            `int`: public_id of the created DocapiTemplate
        """
        try:
            if isinstance(data, dict):
                new_object = DocapiTemplate(**data)
            else:
                new_object: DocapiTemplate = data

            return self.insert(new_object.to_database())
        except Exception as err:
            raise DocapiTemplatesManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_new_docapi_public_id(self) -> int:
        """
        Gets the next couter for the public_id from database and increases it

        Returns:
            int: The next public_id for DocapiTemplate
        """
        return self.get_next_public_id()


    def get_template(self, public_id: int) -> DocapiTemplate:
        """
        Retrieve a single DocapiTemplate from the database

        Args:
            public_id (int): public_id of the requested DocapiTemplate

        Raises:
            DocapiTemplatesManagerGetError: When the DocApiTemplate could not be retrieved
            DocapiTemplatesManagerGetError: When the initialisation of the DocApiTemplate failed

        Returns:
            DocapiTemplate: The requested DocapiTemplate
        """
        try:
            result = self.get_one(public_id)

            return DocapiTemplate(**result)
        except Exception as err:
            raise DocapiTemplatesManagerGetError(str(err)) from err


    def get_templates(self, builder_params: BuilderParameters) -> IterationResult[DocapiTemplate]:
        """
        Retrieve multiple DocapiTemplates matching the builder params

        Args:
            `builder_params` (BuilderParameters): Filter for DocapiTemplates

        Raises:
            `DocapiTemplatesManagerIterationError`: When iteration failed
            `DocapiTemplatesManagerIterationError`: When an unexpected error occured

        Returns:
            `IterationResult[DocapiTemplate]`: _description_
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[DocapiTemplate] = IterationResult(aggregation_result, total,
                                                                                DocapiTemplate)

            return iteration_result
        except Exception as err:
            raise DocapiTemplatesManagerIterationError(str(err)) from err


    def get_templates_by(self, **requirements) -> list[DocapiTemplate]:
        """
        Get multiple DocapiTemplates from the database based on the requirements filter

        Raises:
            DocapiTemplatesManagerGetError: When an exception occurs while retrieving the DocapiTemplates

        Returns:
            list[DocapiTemplate]: List of DocapiTemplates
        """
        try:
            ack: list = []
            templates = self.get_many(**requirements)

            for template in templates:
                ack.append(DocapiTemplate(**template))

            return ack
        except Exception as err:
            raise DocapiTemplatesManagerGetError(err) from err


    def get_template_by_name(self, **requirements) -> DocapiTemplate:
        """
        Retrieve a DocapiTemplate by requirements

        Raises:
            `DocapiTemplatesManagerGetError`: When more than one DocapiTemplate matches the filter
            `DocapiTemplatesManagerGetError`: When the DocapiTemplates could not be retrieved
            `DocapiTemplatesManagerGetError`: When no DocapiTemplate matches the filter

        Returns:
            `DocapiTemplate`: The requested DocapiTemplate
        """
        try:
            templates = self.get_many(collection=DocapiTemplate.COLLECTION, limit=1, **requirements)

            if len(templates) > 0:
                return DocapiTemplate(**templates[0])

            if not len(templates) == 0:
                raise DocapiTemplatesManagerGetError('More than 1 type matches this requirement')

            raise DocapiTemplatesManagerGetError('No document matches the filter!')
        except Exception as err:
            raise DocapiTemplatesManagerGetError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_template(self, data: DocapiTemplate | dict) -> bool:
        """
        Update a DocapiTemplate in the database

        Args:
            data (DocapiTemplate | dict): new data for the DocapiTemplate

        Raises:
            DocapiTemplatesManagerUpdateError: When the DocapiTemplate could not be updated

        Returns:
            bool: If the true then the update was successful
        """
        try:
            if isinstance(data, dict):
                update_object = DocapiTemplate(**data)
            elif isinstance(data, DocapiTemplate):
                update_object = data
            else:
                raise DocapiTemplatesManagerUpdateError("Could not initialise DocapiTemplate with given data!")

            ack = self.update(
                    criteria={'public_id':update_object.get_public_id()},
                    data=update_object.to_database()
                  )

            return ack.acknowledged
        except Exception as err:
            raise DocapiTemplatesManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_template(self, public_id: int) -> bool:
        """
        Deletes a single DocapiTemplate with the given public_id

        Args:
            `public_id` (int): public_id of the DocapiTemplate which should be deleted

        Raises:
            `DocapiTemplatesManagerDeleteError`: When deletion fails

        Returns:
            `bool`: True if deletion was succesful
        """
        try:
            return self.delete({'public_id': public_id})
        except BaseManagerDeleteError as err:
            raise DocapiTemplatesManagerDeleteError(err) from err
