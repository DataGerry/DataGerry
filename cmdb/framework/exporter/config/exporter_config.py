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
# -------------------------------------------------------------------------------------------------------------------- #

class ExporterConfig:
    """
    Carries the configuration for an object export: the collection parameters (filter / sort / order)
    used to fetch the objects, and the optional query parameters (e.g. classname, zip, metadata, view)
    consumed by the chosen export format
    """
    def __init__(self, parameters: CollectionParameters, options: dict | None = None) -> None:
        """
        Args:
            parameters (CollectionParameters): Filter / sort / order options for the object query
            options (dict | None): Optional export parameters (classname, zip, metadata, view, ...)
        """
        self.parameters: CollectionParameters = parameters
        self.options: dict | None = options
