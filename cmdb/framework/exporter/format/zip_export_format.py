# DataGerry - OpenSource Enterprise CMDB
# Copyright (C)  becon GmbH
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
Implementation of ZipExportFormat
"""
import logging
import io
import zipfile

from cmdb.utils.helpers import load_class
from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ZipExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ZipExportFormat(BaseExporterFormat):
    """
    The zip export format class

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "zip"
    LABEL = "ZIP"
    MULTITYPE_SUPPORT = True
    ICON = "file-archive"
    DESCRIPTION = "Export Zipped Files"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args):
        """
        Export a zip file, containing the object list sorted by type in several files

        Args:
            data: List of objects to be exported
            args: the filetype with which the objects are stored
        Returns:
            zip file containing object files separated by types
        """
        # check what export type is requested and intitializes a new zip file in memory
        export_type = load_class(f'cmdb.framework.exporter.format.{args[0].get("classname", "")}')()
        zipped_file = io.BytesIO()

        # Build .zip file
        with zipfile.ZipFile(zipped_file, "a", zipfile.ZIP_DEFLATED, False) as f:
            # Enters loop until the object list is empty
            while len(data) > 0:
                # Set what type the loop filters to and makes an empty list
                type_id = data[len(data) - 1].type_information['type_id']
                type_name = data[len(data) - 1].type_information['type_name']
                type_list = []

                # Filters object list to the current type_id and inserts it into type_list
                # When an object is inserted into type_list it gets deleted from object_list
                for i in range(len(data) - 1, -1, -1):
                    if data[i].type_information['type_id'] == type_id:
                        type_list.append(data[i])
                        del data[i]

                # Runs the requested export function and returns the output in the export variable
                export = export_type.export(type_list)

                # check if export output is a string, bytes or a file and inserts it into the zip file
                if isinstance(export, (str, bytes)):
                    f.writestr((type_name + "_ID_" + str(type_id) + "." + export_type.FILE_EXTENSION).format(i), export)
                else:
                    f.writestr((type_name + "_ID_" + str(type_id) + "." + export_type.FILE_EXTENSION).format(i),
                               export.getvalue())

        # returns zipped file
        zipped_file.seek(0)

        return zipped_file
