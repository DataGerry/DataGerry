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
Implementation of CsvObjectImporterConfig
"""
from cmdb.framework.importer.content_types import CSVContent
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                            CsvObjectImporterConfig - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvObjectImporterConfig(ObjectImporterConfig, CSVContent):
    """
    Configuration class for importing CmdbObjects from a CSV file

    CSV imports require a manual column-to-field mapping (``MANUALLY_MAPPING = True``); the mapping
    list and remaining parameters are handled by the inherited ObjectImporterConfig constructor.

    Attributes:
        MANUALLY_MAPPING (bool): Indicates if manual mapping is required
    """
    MANUALLY_MAPPING = True
