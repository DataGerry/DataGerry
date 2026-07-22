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
This module contains the implementation of the DocapiTemplatesManager
"""
from logging import Logger, getLogger
<<<<<<< HEAD
from typing import Optional, Any
=======
from typing import Any
>>>>>>> origin/version-3.2

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.docapi_templates_manager import (
    DOCAPI_TEMPLATES_MANAGER_ERRORS,
    DocapiTemplatesManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)
<<<<<<< HEAD
=======

# MongoDB projection for the minimal template representation - only public_id and label are read
# (``_id`` excluded), for lightweight listings that do not need the full template document
MINIMAL_TEMPLATE_PROJECTION: dict[str, int] = {'public_id': 1, 'label': 1, '_id': 0}
>>>>>>> origin/version-3.2

# -------------------------------------------------------------------------------------------------------------------- #
#                                            DocapiTemplatesManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class DocapiTemplatesManager(GenericManager):
    """
    Manages DocapiTemplate documents on top of GenericManager

    Keeps the named public API (``insert_template`` / ``get_template`` / ``get_templates`` /
    ``update_template`` / ``delete_template``) used by the existing route call sites, delegating the
    CRUD + per-operation error wrapping to GenericManager. Adds the docapi-specific read helpers
    ``get_templates_by`` and ``get_template_by_name``

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the DocapiTemplatesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the 'dbm' should connect to. Only used in CLOUD_MODE

        Raises:
            DocapiTemplatesManagerInitError: If the DocapiTemplatesManager could not be initialised
        """
        super().__init__(dbm, DocapiTemplate, DOCAPI_TEMPLATES_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_template(self, data: DocapiTemplate | dict[str, Any]) -> int:
        """
        Insert a new DocapiTemplate into the database

        Args:
            data (DocapiTemplate | dict[str, Any]): The data of the new DocapiTemplate

        Raises:
            DocapiTemplatesManagerInsertError: When the creation of the DocapiTemplate failed

        Returns:
            int: public_id of the created DocapiTemplate
        """
        if isinstance(data, dict):
            data = DocapiTemplate(**data)

        return self.insert_item(data)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_new_docapi_public_id(self) -> int:
        """
        Gets the next public_id counter value from the database and increases it

        Returns:
            int: The next public_id for a DocapiTemplate
        """
        return self.get_next_public_id(inc_id=True)


    def get_template(self, public_id: int) -> DocapiTemplate | None:
        """
        Retrieve a single DocapiTemplate from the database

        Args:
            public_id (int): public_id of the requested DocapiTemplate

        Raises:
            DocapiTemplatesManagerGetError: When the DocapiTemplate could not be retrieved

        Returns:
            DocapiTemplate | None: The requested DocapiTemplate, or None if no template has that id
        """
        return self.get_item(public_id, as_dict=False)


    def get_templates(self, builder_params: BuilderParameters) -> IterationResult[DocapiTemplate]:
        """
        Retrieve multiple DocapiTemplates matching the builder params

        Args:
            builder_params (BuilderParameters): Filter, sort and pagination parameters

        Raises:
            DocapiTemplatesManagerIterationError: When the iteration failed

        Returns:
            IterationResult[DocapiTemplate]: All DocapiTemplates matching the filter
        """
        return self.iterate_items(builder_params)


    def get_templates_by(self, **requirements: Any) -> list[DocapiTemplate]:
        """
        Get multiple DocapiTemplates from the database based on the requirements filter

        Args:
            **requirements (Any): Field/value pairs the returned DocapiTemplates must match

        Raises:
            DocapiTemplatesManagerGetError: When an exception occurs while retrieving the DocapiTemplates

        Returns:
            list[DocapiTemplate]: List of matching DocapiTemplates
        """
        try:
            templates = self.get_many(**requirements)

            return [DocapiTemplate.from_data(template) for template in templates]
        except Exception as err:
            raise DocapiTemplatesManagerGetError(str(err)) from err


    def get_minimal_templates_by(self, **requirements: Any) -> list[dict[str, Any]]:
        """
        Retrieve a minimal representation of DocapiTemplates matching the requirements filter

        Only the public_id and label are read from the database (server-side projection), for
        lightweight listings that do not need the full template document

        Args:
            **requirements (Any): Field/value pairs the returned DocapiTemplates must match

        Raises:
            DocapiTemplatesManagerGetError: When an exception occurs while retrieving the DocapiTemplates

        Returns:
            list[dict[str, Any]]: Matching templates as {'public_id': ..., 'label': ...} dicts
        """
        try:
            return self.find(criteria=requirements, projection=MINIMAL_TEMPLATE_PROJECTION)
        except Exception as err:
            raise DocapiTemplatesManagerGetError(str(err)) from err


    def get_template_by_name(self, **requirements: Any) -> DocapiTemplate | None:
        """
        Retrieve a single DocapiTemplate matching the requirements filter

        Args:
            **requirements (Any): Field/value pairs the returned DocapiTemplate must match

        Raises:
            DocapiTemplatesManagerGetError: When the DocapiTemplate could not be retrieved

        Returns:
            DocapiTemplate | None: The first matching DocapiTemplate, or None if none matches
        """
        try:
            templates = self.get_many(limit=1, **requirements)

            if templates:
                return DocapiTemplate.from_data(templates[0])

            return None
        except Exception as err:
            raise DocapiTemplatesManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_template(self, data: DocapiTemplate | dict[str, Any]) -> None:
        """
        Update a DocapiTemplate in the database

        The DocapiTemplate is identified by the ``public_id`` carried in ``data``. Updating an id
        that does not exist is a no-op (the underlying update does not upsert)

        Args:
            data (DocapiTemplate | dict[str, Any]): New data for the DocapiTemplate

        Raises:
            DocapiTemplatesManagerUpdateError: When the DocapiTemplate could not be updated
        """
        if isinstance(data, dict):
            data = DocapiTemplate(**data)

        self.update_item(data.get_public_id(), data)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_template(self, public_id: int) -> bool:
        """
        Deletes a single DocapiTemplate with the given public_id

        Args:
            public_id (int): public_id of the DocapiTemplate which should be deleted

        Raises:
            DocapiTemplatesManagerDeleteError: When deletion fails

        Returns:
            bool: True if a document was actually removed, False otherwise
        """
        return self.delete_item(public_id)
