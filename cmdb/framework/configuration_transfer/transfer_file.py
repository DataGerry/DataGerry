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
Builds a configuration transfer file and judges the envelope of an uploaded one

The envelope rules only judge the SHAPE a file has - which keys exist and what kind of value each holds. What the
documents inside a component's `items` must look like is the component's own rule (`TransferComponent`). Every rule
returns its problems instead of raising, so an import can answer every problem of a file at once
"""
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    TRANSFER_FORMAT_VERSION,
    TransferFileKey,
    TransferSectionKey,
    FILE_NOT_AN_OBJECT,
    MISSING_FILE_KEY,
    UNKNOWN_FILE_KEY,
    FORMAT_VERSION_MISMATCH,
    DB_VERSION_NOT_A_NUMBER,
    EXPORTED_AT_NOT_A_STRING,
    COMPONENTS_NOT_AN_OBJECT,
    MISSING_COMPONENT,
    UNKNOWN_COMPONENT,
    SECTION_NOT_AN_OBJECT,
    MISSING_SECTION_KEY,
    UNKNOWN_SECTION_KEY,
    COUNTER_NOT_A_NUMBER,
    ITEMS_NOT_A_LIST,
    ITEM_NOT_AN_OBJECT,
    DB_VERSION_MISMATCH,
    DB_VERSION_TOO_NEW,
)
from cmdb.utils import is_non_blank_string
# -------------------------------------------------------------------------------------------------------------------- #

def is_strict_int(value: Any) -> bool:
    """
    Reports whether a value is a JSON integer

    A transfer file is written by DataGerry itself, so a number arrives as an int and nothing else: a float, a
    numeric string and a boolean (an int subclass in Python) are all refused

    Args:
        value (Any): The value to test

    Returns:
        bool: True for an int that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


def build_component_section(counter: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Builds one component's section of a transfer file

    Args:
        counter (int): The component's public_id counter
        items (list[dict[str, Any]]): The component's documents

    Returns:
        dict[str, Any]: The section
    """
    return {
        TransferSectionKey.COUNTER.value: counter,
        TransferSectionKey.ITEMS.value: items,
    }


def build_transfer_file(
        db_version: int,
        components: dict[str, dict[str, Any]],
        exported_at: datetime | None = None) -> dict[str, Any]:
    """
    Builds a transfer file around the sections of its components

    Args:
        db_version (int): The updater version of the exporting database
        components (dict[str, dict[str, Any]]): Each component's section, keyed by its name
        exported_at (datetime | None): The export time; None stamps the current UTC time

    Returns:
        dict[str, Any]: The transfer file
    """
    stamp: datetime = exported_at or datetime.now(timezone.utc)

    return {
        TransferFileKey.FORMAT_VERSION.value: TRANSFER_FORMAT_VERSION,
        TransferFileKey.DB_VERSION.value: db_version,
        TransferFileKey.EXPORTED_AT.value: stamp.isoformat(),
        TransferFileKey.COMPONENTS.value: components,
    }

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    ENVELOPE RULES                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def find_key_problems(document: dict[str, Any], expected: Iterable[str], missing: str, unknown: str,
                      **context: str) -> list[str]:
    """
    Names every expected key a document lacks and every key it has that is not expected

    Args:
        document (dict[str, Any]): The document to check
        expected (Iterable[str]): The keys it must have, and the only ones it may have
        missing (str): The message template for a missing key, formatted with `key` and `context`
        unknown (str): The message template for an unknown key, formatted with `key` and `context`
        **context (str): Further values the templates name

    Returns:
        list[str]: The problems, missing keys first, each group in a stable order
    """
    expected_keys: list[str] = list(expected)
    problems: list[str] = [missing.format(key=key, **context) for key in expected_keys if key not in document]
    problems += [unknown.format(key=key, **context) for key in sorted(document) if key not in expected_keys]

    return problems


def format_version_problem(value: Any) -> str | None:
    """
    Judges a file's `format_version`

    Args:
        value (Any): The stored value

    Returns:
        str | None: The problem, or None when it is the version this code reads
    """
    if is_strict_int(value) and value == TRANSFER_FORMAT_VERSION:
        return None

    return FORMAT_VERSION_MISMATCH.format(key=TransferFileKey.FORMAT_VERSION.value, expected=TRANSFER_FORMAT_VERSION)


def db_version_problem(value: Any) -> str | None:
    """
    Judges the shape of a file's `db_version` - whether it MATCHES the target is `db_version_mismatch`

    Args:
        value (Any): The stored value

    Returns:
        str | None: The problem, or None for a positive whole number
    """
    if is_strict_int(value) and value > 0:
        return None

    return DB_VERSION_NOT_A_NUMBER.format(key=TransferFileKey.DB_VERSION.value)


def exported_at_problem(value: Any) -> str | None:
    """
    Judges a file's `exported_at`

    The stamp is informational - nothing is derived from it - so any non-blank string passes

    Args:
        value (Any): The stored value

    Returns:
        str | None: The problem, or None for a non-blank string
    """
    if is_non_blank_string(value):
        return None

    return EXPORTED_AT_NOT_A_STRING.format(key=TransferFileKey.EXPORTED_AT.value)


def find_section_problems(name: str, section: Any) -> list[str]:
    """
    Judges the envelope of one component's section: its keys, its counter, and that each item is an object

    Args:
        name (str): The component's name
        section (Any): The stored section

    Returns:
        list[str]: The problems, empty when the section's envelope is usable
    """
    if not isinstance(section, dict):
        return [SECTION_NOT_AN_OBJECT.format(name=name)]

    problems: list[str] = find_key_problems(section, [key.value for key in TransferSectionKey], MISSING_SECTION_KEY,
                                            UNKNOWN_SECTION_KEY, name=name)
    counter_key: str = TransferSectionKey.COUNTER.value
    items_key: str = TransferSectionKey.ITEMS.value

    if counter_key in section and not (is_strict_int(section[counter_key]) and section[counter_key] >= 0):
        problems.append(COUNTER_NOT_A_NUMBER.format(name=name, key=counter_key))

    if items_key in section:
        items: Any = section[items_key]

        if not isinstance(items, list):
            problems.append(ITEMS_NOT_A_LIST.format(name=name, key=items_key))
        else:
            problems += [ITEM_NOT_AN_OBJECT.format(index=index, name=name)
                         for index, item in enumerate(items) if not isinstance(item, dict)]

    return problems


def find_components_problems(components: Any, component_names: Iterable[str]) -> list[str]:
    """
    Judges a file's `components`: every registered component present, nothing else, each section usable

    An export always writes every registered component, so a missing one means the file was not written by this
    version - an empty component is a section with no items, never an absent one

    Args:
        components (Any): The stored `components`
        component_names (Iterable[str]): The registered components' names

    Returns:
        list[str]: The problems, empty when every section's envelope is usable
    """
    if not isinstance(components, dict):
        return [COMPONENTS_NOT_AN_OBJECT.format(key=TransferFileKey.COMPONENTS.value)]

    names: list[str] = list(component_names)
    problems: list[str] = [MISSING_COMPONENT.format(name=name) for name in names if name not in components]
    problems += [UNKNOWN_COMPONENT.format(name=name) for name in sorted(components) if name not in names]

    for name in names:
        if name in components:
            problems += find_section_problems(name, components[name])

    return problems


def find_transfer_file_problems(data: Any, component_names: Iterable[str]) -> list[str]:
    """
    Judges the envelope of an uploaded transfer file

    Collects every problem rather than stopping at the first, so the caller can report them together. Only a file
    that is not a JSON object stops early - none of the other rules can be asked of it

    Args:
        data (Any): The parsed upload
        component_names (Iterable[str]): The registered components' names

    Returns:
        list[str]: The problems, empty when the envelope is usable
    """
    if not isinstance(data, dict):
        return [FILE_NOT_AN_OBJECT]

    problems: list[str] = find_key_problems(data, [key.value for key in TransferFileKey], MISSING_FILE_KEY,
                                            UNKNOWN_FILE_KEY)
    value_rules: list[tuple[TransferFileKey, Callable[[Any], str | None]]] = [
        (TransferFileKey.FORMAT_VERSION, format_version_problem),
        (TransferFileKey.DB_VERSION, db_version_problem),
        (TransferFileKey.EXPORTED_AT, exported_at_problem),
    ]

    for key, rule in value_rules:
        if key.value in data:
            problem: str | None = rule(data[key.value])

            if problem:
                problems.append(problem)

    if TransferFileKey.COMPONENTS.value in data:
        problems += find_components_problems(data[TransferFileKey.COMPONENTS.value], component_names)

    return problems


def db_version_mismatch(file_version: int, target_version: int) -> str | None:
    """
    Judges whether a file's `db_version` matches the importing database's updater version

    Only an exact match passes: a file from an older version carries documents in a shape this database no longer
    stores, one from a newer version documents it does not know yet

    Args:
        file_version (int): The file's `db_version`
        target_version (int): The importing database's current updater version

    Returns:
        str | None: The problem, or None when the versions match
    """
    if file_version == target_version:
        return None

    return DB_VERSION_MISMATCH.format(file_version=file_version, target_version=target_version)


def db_version_too_new(file_version: int, target_version: int) -> str | None:
    """
    Judges whether a file was exported from a newer version than the importing database's

    An older file is migrated before it is judged (`configuration_staging`); a newer one carries document shapes this
    version does not know, so nothing could migrate it

    Args:
        file_version (int): The file's `db_version`
        target_version (int): The importing database's current updater version

    Returns:
        str | None: The problem, or None when the file is of the same or an older version
    """
    if file_version <= target_version:
        return None

    return DB_VERSION_TOO_NEW.format(file_version=file_version, target_version=target_version)
