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
Implementation of ExporterConfig
"""
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
# -------------------------------------------------------------------------------------------------------------------- #

class ExporterConfig:
    """
    Base class for exporter configurations
    """
    def __init__(self, parameters: CollectionParameters, options: dict = None) -> None:
        """
        Args:
            parameters (CollectionParameters): Filter and sort options for a collection
            options: dict of optional parameters
        """
        self.parameters: CollectionParameters = parameters
        self.options: dict | None = options
        self.config_type = ExporterConfigType.NATIVE
