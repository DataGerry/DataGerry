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
Implementation of SupportedExporterExtension - the catalogue behind ``GET /exporter/extensions``

The catalogue lists the export formats a user can PICK, each with the metadata the frontend's export menus draw it
with (``ExporterExtensionKey``: extension, label, icon, multiTypeSupport, helperText, active). Two things are
deliberately not in it:

* **the view.** Every format exports either view - ``?view=native`` (the stored values, for re-import) or
  ``?view=render`` (the display values) - and the user chooses it per export ("Raw" / "Customer" export in the
  menus), so a per-format ``view`` would be meaningless. The frontend model's ``view`` is that client-side choice
* **ZIP.** ZIP is not a format but a wrapper around one: ``zip=true`` packs the format ``classname`` names into one
  archive, one file per type. Listed as an entry it would offer a ZIP with nothing to pack, so it is never in the
  catalogue and cannot be named as a ``classname`` either
"""
from logging import Logger, getLogger
from functools import lru_cache
from typing import Any

from cmdb.utils import load_class
from cmdb.framework.exporter.exporter_constants import EXPORT_FORMAT_MODULE_PREFIX, ExporterExtensionKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


@lru_cache(maxsize=None)
def _build_extension_catalogue(extensions: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    """
    Builds the export-format catalogue for the given format class names

    Each entry carries the format's frontend metadata read from its class attributes. The result is
    cached per unique `extensions` tuple: the format classes and their metadata are static, so the
    catalogue only ever has to be built once per distinct set of extensions.

    Args:
        extensions (tuple[str, ...]): The export format class names to describe

    Returns:
        tuple[dict[str, Any], ...]: One metadata dict per format (see `ExporterExtensionKey`)
    """
    catalogue: list[dict[str, Any]] = []

    for extension in extensions:
        format_class = load_class(f'{EXPORT_FORMAT_MODULE_PREFIX}{extension}')

        catalogue.append({
            ExporterExtensionKey.EXTENSION.value: extension,
            ExporterExtensionKey.LABEL.value: format_class.LABEL,
            ExporterExtensionKey.ICON.value: format_class.ICON,
            ExporterExtensionKey.MULTI_TYPE_SUPPORT.value: format_class.MULTITYPE_SUPPORT,
            ExporterExtensionKey.HELPER_TEXT.value: format_class.DESCRIPTION,
            ExporterExtensionKey.ACTIVE.value: format_class.ACTIVE,
        })

    return tuple(catalogue)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          SupportedExporterExtension - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class SupportedExporterExtension:
    """
    Maintains the list of supported export format class names (CSV, JSON, XLSX, XML)

    The same list is the formats a ZIP may pack and the formats a request's ``classname`` may name - see the module
    docstring for why neither the view nor ZIP is part of it
    """

    DEFAULT_EXTENSIONS: list[str] = [
        "CsvExportFormat",
        "JsonExportFormat",
        "XlsxExportFormat",
        "XmlExportFormat"
    ]

    def __init__(self, extensions: list[str] | None = None) -> None:
        """
        Initializes the SupportedExporterExtension with the default plus any custom extensions

        Args:
            extensions (list[str] | None): Additional export format class names to include
        """
        self.extensions: list[str] = self.DEFAULT_EXTENSIONS + (extensions or [])


    def get_extensions(self) -> list[str]:
        """
        Retrieves the list of supported export format class names

        Returns:
            list[str]: The export format class names (e.g. `"CsvExportFormat"`), NOT file extensions
        """
        return self.extensions


    def convert_to(self) -> list[dict[str, Any]]:
        """
        Describes the supported export formats as frontend-ready metadata dicts

        Returns a fresh list of dicts (one per format) so callers can safely mutate the result without
        affecting the cached catalogue built by `_build_extension_catalogue`.

        Returns:
            list[dict[str, Any]]: One metadata dict per supported export format (see `ExporterExtensionKey`)
        """
        return [dict(entry) for entry in _build_extension_catalogue(tuple(self.extensions))]
