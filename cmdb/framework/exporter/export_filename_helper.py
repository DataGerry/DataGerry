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
Naming of exported files (framework layer)

Both export paths - the object export engine (`BaseExportWriter.export`) and the CmdbType export
(`exporter_helper.build_types_json_export_response`) - build their download filename here, so the
timezone, the layout and the sanitising are one decision instead of two independent ones.

The layout is `<timestamp>_<kind>_<subject>[_readable].<extension>`:

    2026_07_21-13_05_00_objects_router.csv            one type
    2026_07_21-13_05_00_objects_router_readable.csv   ... exported for reading, NOT re-importable
    2026_07_21-13_05_00_objects_3-types.json          a selection spanning several types
    2026_07_21-13_05_00_objects_no-objects.json       a filter that matched nothing
    2026_07_21-13_05_00_types_47.json                 47 CmdbTypes

The timestamp leads so a downloads folder sorts chronologically by name; the kind and subject follow so
a file can be identified without opening it - before this, every export of every kind was named by its
timestamp alone.

NOTE the frontend currently names the downloaded file itself and discards the name sent in the
Content-Disposition header, so these names only become visible once it adopts the server's.
"""
import re
from datetime import datetime, timezone

from cmdb.framework.exporter.exporter_constants import (
    EXPORT_FILENAME_TIMESTAMP_FMT,
    EXPORT_FILENAME_PART_SEPARATOR,
    EXPORT_FILENAME_ALLOWED_PATTERN,
    EXPORT_FILENAME_REPLACEMENT,
    EXPORT_FILENAME_SUBJECT_MAX_LENGTH,
    EXPORT_FILENAME_MAX_LENGTH,
    EXPORT_FILENAME_READABLE_MARKER,
    EXPORT_FILENAME_TEMPLATE_MARKER,
    EXPORT_KIND_OBJECTS,
    EXPORT_KIND_TYPES,
    EXPORT_SUBJECT_MANY_TYPES_TEMPLATE,
    EXPORT_SUBJECT_NO_OBJECTS,
)
# -------------------------------------------------------------------------------------------------------------------- #

def build_export_filename_timestamp() -> str:
    """
    Builds the timestamp that leads an exported file's name

    The stamp is taken in UTC rather than the server's local timezone, so exports of the same system
    sort and compare consistently no matter where the instance runs. Note the format carries no
    timezone marker, so the value is only meaningful as an identifier, not as a displayed local time

    Returns:
        str: The current UTC time formatted per EXPORT_FILENAME_TIMESTAMP_FMT, e.g. `2026_07_27-13_05_00`
    """
    return datetime.now(timezone.utc).strftime(EXPORT_FILENAME_TIMESTAMP_FMT)


def sanitize_filename_part(value: str) -> str:
    """
    Reduces one filename part to a lower-case, ASCII, separator-safe token

    A CmdbType name is free text: it may carry spaces, umlauts, path separators, quotes or - in
    principle - a line break. The value ends up BOTH in a filesystem name and in a Content-Disposition
    header, so everything outside the allowed set collapses into a single replacement character and the
    result is length-capped. An empty or fully-replaced value yields an empty string, which the caller
    treats as "no usable subject"

    Args:
        value (str): The raw part, e.g. a CmdbType name

    Returns:
        str: The sanitised token, at most EXPORT_FILENAME_SUBJECT_MAX_LENGTH characters
    """
    reduced = re.sub(EXPORT_FILENAME_ALLOWED_PATTERN, EXPORT_FILENAME_REPLACEMENT, (value or '').lower())
    trimmed = reduced.strip(f'{EXPORT_FILENAME_REPLACEMENT}.')[:EXPORT_FILENAME_SUBJECT_MAX_LENGTH]

    return trimmed.strip(f'{EXPORT_FILENAME_REPLACEMENT}.')


def build_object_export_subject(type_names: list[str]) -> str:
    """
    Names what an object export contains

    One type is named after that type, which is the common case and the only information worth having.
    A selection spanning several types (JSON / XML / ZIP - CSV and XLSX refuse a mixed selection) is
    named by their COUNT rather than by a list, so the name stays short and never has to be elided. A
    filter that matched no object has no type to name at all

    Args:
        type_names (list[str]): The distinct CmdbType names of the exported objects

    Returns:
        str: The subject part of the filename
    """
    if not type_names:
        return EXPORT_SUBJECT_NO_OBJECTS

    if len(type_names) > 1:
        return EXPORT_SUBJECT_MANY_TYPES_TEMPLATE.format(count=len(type_names))

    # A name made up entirely of replaced characters leaves nothing to identify the type by, so the
    # count form stands in rather than a bare separator
    return sanitize_filename_part(type_names[0]) or EXPORT_SUBJECT_MANY_TYPES_TEMPLATE.format(count=1)


def build_export_filename(kind: str, subject: str, file_extension: str, human_readable: bool = False) -> str:
    """
    Assembles a full export filename from its parts

    Args:
        kind (str): What was exported (EXPORT_KIND_OBJECTS / EXPORT_KIND_TYPES)
        subject (str): What the export contains (a type name, a count, ...)
        file_extension (str): The format's file extension, without the leading dot
        human_readable (bool): Whether to mark the file as a presentation export. Defaults to False

    Returns:
        str: The filename, including the extension
    """
    parts: list[str] = [build_export_filename_timestamp(), kind, subject]

    if human_readable:
        parts.append(EXPORT_FILENAME_READABLE_MARKER)

    stem = EXPORT_FILENAME_PART_SEPARATOR.join(part for part in parts if part)[:EXPORT_FILENAME_MAX_LENGTH]

    return f'{stem}.{file_extension}'


def build_object_export_filename(
        type_names: list[str],
        file_extension: str,
        human_readable: bool = False,
    ) -> str:
    """
    Builds the download filename of an object export

    Args:
        type_names (list[str]): The distinct CmdbType names of the exported objects
        file_extension (str): The format's file extension, without the leading dot
        human_readable (bool): Whether this is a presentation export (not re-importable). Defaults to
                               False

    Returns:
        str: e.g. `2026_07_21-13_05_00_objects_router_readable.csv`
    """
    return build_export_filename(
        EXPORT_KIND_OBJECTS,
        build_object_export_subject(type_names),
        file_extension,
        human_readable,
    )


def build_object_template_filename(type_label: str, file_extension: str) -> str:
    """
    Builds the download filename of an object-import template

    The type is named by its LABEL rather than its name: a template is a document handed to a person, and
    the label is what that person sees in the UI. The name closes with the template marker, so a template
    and an export of the same type taken in the same second stay distinguishable. A label that sanitises
    away to nothing leaves the timestamp and the marker, which still identifies the file as a template

    Args:
        type_label (str): Label of the CmdbType the template is for
        file_extension (str): The format's file extension, without the leading dot

    Returns:
        str: e.g. `2026_07_21-13_05_00_router-core_template.csv`
    """
    parts: list[str] = [
        build_export_filename_timestamp(),
        sanitize_filename_part(type_label),
        EXPORT_FILENAME_TEMPLATE_MARKER,
    ]

    stem = EXPORT_FILENAME_PART_SEPARATOR.join(part for part in parts if part)[:EXPORT_FILENAME_MAX_LENGTH]

    return f'{stem}.{file_extension}'


def build_type_export_filename(type_count: int, file_extension: str) -> str:
    """
    Builds the download filename of a CmdbType export

    The subject is the number of exported types: unlike an object export, which is usually one type, a
    type export is a catalogue slice whose size is the useful information

    Args:
        type_count (int): How many CmdbTypes the export contains
        file_extension (str): The format's file extension, without the leading dot

    Returns:
        str: e.g. `2026_07_21-13_05_00_types_47.json`
    """
    return build_export_filename(EXPORT_KIND_TYPES, str(type_count), file_extension)
