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
Implementation of BaseExportWriter
"""
from logging import Logger, getLogger
import datetime
from flask import Response

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject
from cmdb.framework.rendering.render_list import RenderList
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.exporter.config.exporter_config import ExporterConfig
from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               BaseExportWriter - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class  BaseExportWriter:
    """
    The base class for export writers
    """

    def __init__(self, export_format: BaseExporterFormat, export_config: ExporterConfig):
        """
        Initialises the BaseExportWriter

        Args:
            export_format (BaseExporterFormat): The format in which data will be exported (CSV, JSON, XLSX, XML)
            export_config (ExporterConfig): Configuration parameters such as filters or zip settings
        """
        self.export_format: BaseExporterFormat = export_format
        self.export_config: ExporterConfig = export_config
        self.data: list[RenderResult] = [] #Storage for exportable data


    def from_database(
            self,
            dbm: MongoDatabaseManager,
            user: CmdbUser,
            permission: AccessControlPermission,
            db_name: str | None = None
        ) -> None:
        """
        Retrieves all objects from the collection and processes them for export

        Args:
            dbm (MongoDatabaseManager): The database manager instance
            user (CmdbUser): The user requesting the data
            permission (AccessControlPermission): The user's access permissions
        """
        objects_manager = ObjectsManager(dbm, db_name)
        export_params = self.export_config.parameters

        builder_params = BuilderParameters(
            criteria=export_params.filter,
            sort=export_params.sort,
            order=export_params.order
        )

        # Fetch objects from the database
        objects: list[CmdbObject] = objects_manager.iterate(builder_params, user, permission).results

        # Process and store exportable data
        self.data = RenderList(objects, user, True).render_result_list(raw=False)


    def export(self) -> Response:
        """
        Exports the collected data in the specified format and returns a Flask Response

        Returns:
            Response: A Flask Response object containing the exported data
        """
        conf_option = self.export_config.options
        timestamp = datetime.datetime.now().strftime('%Y_%m_%d-%H_%M_%S')

        # Generate the export content
        export_content  = self.export_format.export(self.data, conf_option)

        file_extension = self.export_format.__class__.FILE_EXTENSION

        return Response(
            export_content,
            mimetype="text/" + self.export_format.__class__.FILE_EXTENSION,
            headers={
                "Content-Disposition": f"attachment; filename={timestamp}.{file_extension}"
            }
        )
