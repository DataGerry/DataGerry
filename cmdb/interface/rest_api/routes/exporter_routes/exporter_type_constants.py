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
Shared constants for the CmdbType export REST routes

Kept apart from the object-export constants because the two are unrelated: the CmdbType export is a
standalone JSON serialization that deliberately bypasses the object export engine
(`cmdb/framework/exporter`), mirroring the importer side's `importer_constants` /
`importer_type_constants` split
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['TYPE_EXPORT_MIMETYPE', 'TYPE_EXPORT_FILE_EXTENSION', 'TYPE_EXPORT_JSON_INDENT']

# Mimetype + file extension of the CmdbType export (JSON only). These intentionally MIRROR
# JsonExportFormat.MIME_TYPE / .FILE_EXTENSION instead of importing them - coupling the type export to a
# class of the object export engine would undo the separation the whole type-export path is built on.
# test_exporter_type_constants pins the two copies to each other so they cannot silently drift
TYPE_EXPORT_MIMETYPE: str = 'application/json'
TYPE_EXPORT_FILE_EXTENSION: str = 'json'

# Indentation of the exported CmdbType JSON - the export is meant to be read and diffed, not minified
TYPE_EXPORT_JSON_INDENT: int = 2
