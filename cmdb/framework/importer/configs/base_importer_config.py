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
Implementation of BaseImporterConfig
"""
from cmdb.framework.importer.mapper.mapping import Mapping
# -------------------------------------------------------------------------------------------------------------------- #

class BaseImporterConfig:
    """
    Base class for import configurations

    Subclasses may override ``DEFAULT_MAPPING`` to supply the mapping used when no mapping list is
    passed. The object importer configs use two shapes: the CSV/base path builds a fresh ``Mapping``,
    while the JSON config overrides ``DEFAULT_MAPPING`` with a plain ``dict`` describing a fixed
    property/field mapping — hence ``get_mapping()`` may return either a ``Mapping`` or a ``dict``.
    """
    DEFAULT_MAPPING: dict | Mapping | None = None
    MANUALLY_MAPPING: bool = True

    def __init__(self, mapping: list | None = None) -> None:
        """
        Initializes the BaseImporterConfig

        A caller-supplied mapping list is turned into a fresh ``Mapping``. Otherwise the subclass
        ``DEFAULT_MAPPING`` is used if set, else a fresh empty ``Mapping`` — never a shared instance.

        Args:
            mapping (list | None): Optional list of mapping definitions used to build a Mapping
        """
        if mapping:
            resolved: dict | Mapping = Mapping.generate_mapping_from_list(mapping)
        elif self.DEFAULT_MAPPING is not None:
            resolved = self.DEFAULT_MAPPING
        else:
            resolved = Mapping()

        self.mapping: dict | Mapping = resolved


    def get_mapping(self) -> dict | Mapping:
        """
        Returns the current mapping configuration

        Returns:
            dict | Mapping: The mapping associated with this configuration (a ``Mapping``, or the
            subclass's ``dict`` default as used by the JSON importer config)
        """
        return self.mapping
