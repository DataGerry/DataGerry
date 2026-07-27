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
from flask import Response

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import ObjectsManager
from cmdb.manager.locations_manager import LocationsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.rendering.render_list import RenderList
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.exporter.config.exporter_config import ExporterConfig
from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
from cmdb.framework.exporter.exporter_constants import ExporterOptionKey
from cmdb.framework.exporter.export_filename_helper import build_export_filename_timestamp

from cmdb.errors.manager.locations_manager import LocationsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               BaseExportWriter - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseExportWriter:
    """
    Drives an object export: fetches + renders the objects from the database, then serializes them
    through a chosen export format into a downloadable Flask Response
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
        # Kept from `from_database` so a human-readable export can resolve location names (the format
        # classes have no database access)
        self._dbm: MongoDatabaseManager | None = None
        self._db_name: str | None = None


    def from_database(
            self,
            dbm: MongoDatabaseManager,
            user: CmdbUser,
            permission: AccessControlPermission,
            db_name: str | None = None
        ) -> None:
        """
        Retrieves the objects matching the export filter and renders them for export

        The objects are fetched (honouring the configured filter / sort / order and the user's ACL
        permission) and rendered into `self.data` ready for the export format to serialize.

        Args:
            dbm (MongoDatabaseManager): The database manager instance
            user (CmdbUser): The user requesting the data
            permission (AccessControlPermission): The access permission enforced while fetching objects
            db_name (str | None): Target database name (cloud mode); None uses the default database
        """
        self._dbm = dbm
        self._db_name = db_name

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
        timestamp: str = build_export_filename_timestamp()

        # A human-readable export needs location field values resolved to names; the format classes have
        # no database access, so resolve the {public_id: name} map here and pass it through the options
        if BaseExporterFormat.is_human_readable(conf_option):
            conf_option = {**(conf_option or {}),
                           ExporterOptionKey.LOCATION_NAMES.value: self._resolve_location_names()}

        # Generate the export content
        export_content = self.export_format.export(self.data, conf_option)

        file_extension = self.export_format.__class__.FILE_EXTENSION
        mimetype = self.export_format.__class__.MIME_TYPE

        return Response(
            export_content,
            mimetype=mimetype,
            headers={
                "Content-Disposition": f"attachment; filename={timestamp}.{file_extension}"
            }
        )


    def _resolve_location_names(self) -> dict:
        """
        Resolves the names of every location referenced by a location field across the export data

        Collects the location public_ids from all location-typed fields and looks up their
        ``CmdbLocation.name`` (the label shown in the location tree) in a single query. A lookup
        failure is logged and degrades to an empty map so it never fails the export.

        Returns:
            dict: A `{location public_id: location name}` map (empty when there are no locations)
        """
        location_ids = {
            field.get(FieldKey.VALUE.value)
            for obj in self.data
            for field in obj.fields
            if field.get(FieldKey.TYPE.value) == FieldType.LOCATION.value
            and field.get(FieldKey.VALUE.value) not in (None, '')
        }

        if not location_ids:
            return {}

        try:
            locations_manager = LocationsManager(self._dbm, self._db_name)
            locations = locations_manager.get_locations_by(public_id={'$in': list(location_ids)})

            return {location.public_id: location.name for location in locations}
        except LocationsManagerGetError as err:
            LOGGER.error("[_resolve_location_names] Could not resolve location names: %s", err)

            return {}
