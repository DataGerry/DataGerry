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

The envelope is every top-level key with its `information` and `meta` sections and the shell of each component's
section. The envelope rules only judge the SHAPE a file has - which keys exist and what kind of value each holds -
and that the `information` counts match the entries. What the
documents inside a component's `items` must look like is the component's own rule (`TransferComponent`). Every rule
returns its problems instead of raising, so an import can answer every problem of a file at once
"""
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from cerberus import Validator

from cmdb import __version__
from cmdb.models.category_model.category_constants import CategoryKey
from cmdb.framework.configuration_transfer.best_practice_constants import BestPracticeMetaKey
from cmdb.framework.configuration_transfer.best_practice_meta_schema import get_exported_meta_schema
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    TRANSFER_FORMAT_VERSION,
    INFORMATION_NAME_MAX_LENGTH,
    INFORMATION_DESCRIPTION_MAX_LENGTH,
    TransferComponentName,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
    FILE_NOT_AN_OBJECT,
    MISSING_FILE_KEY,
    UNKNOWN_FILE_KEY,
    FORMAT_VERSION_MISMATCH,
    DB_VERSION_NOT_A_NUMBER,
    EXPORTED_AT_NOT_A_STRING,
    FILE_KEY_NOT_AN_OBJECT,
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
    MISSING_SECTION_FIELD,
    UNKNOWN_SECTION_FIELD,
    INFORMATION_NOT_TEXT,
    INFORMATION_NOT_A_STRING,
    INFORMATION_TOO_LONG,
    MISSING_COUNT,
    UNKNOWN_COUNT,
    COUNT_NOT_A_NUMBER,
    COUNT_MISMATCH,
    META_INVALID,
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


def count_component_items(components: dict[str, dict[str, Any]]) -> dict[str, int]:
    """
    Counts the entries of each component's section

    Args:
        components (dict[str, dict[str, Any]]): Each component's section, keyed by its name

    Returns:
        dict[str, int]: The number of entries per component, in the order of the sections
    """
    return {name: len(section[TransferSectionKey.ITEMS.value]) for name, section in components.items()}


def category_names_of(components: dict[str, dict[str, Any]]) -> list[str]:
    """
    Answers the names of the categories a file carries, in the order of its entries

    Args:
        components (dict[str, dict[str, Any]]): Each component's section, keyed by its name

    Returns:
        list[str]: Every category's name that is a non-blank string - none when there is no categories section
    """
    section: dict[str, Any] = components.get(TransferComponentName.CATEGORIES.value, {})
    names: list[Any] = [item.get(CategoryKey.NAME.value) for item in section.get(TransferSectionKey.ITEMS.value, [])]

    return [name for name in names if is_non_blank_string(name)]


def build_information(name: str, description: str, components: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Builds a transfer file's `information` section: what the user says about it plus what the export fills in

    Args:
        name (str): What the exporting user calls the file
        description (str): The exporting user's description of it - empty when none was given
        components (dict[str, dict[str, Any]]): Each component's section, keyed by its name

    Returns:
        dict[str, Any]: The section - the DataGerry release that writes it and the entries per component included
    """
    return {
        TransferInformationKey.NAME.value: name,
        TransferInformationKey.DESCRIPTION.value: description,
        TransferInformationKey.VERSION.value: __version__,
        TransferInformationKey.COUNTS.value: count_component_items(components),
    }


def build_empty_meta(category_names: Iterable[str]) -> dict[str, Any]:
    """
    Builds a transfer file's `meta` section with every value left empty, to be filled in by hand

    Each category of the file gets its entry in `category_descriptions` already, so its name need not be looked up

    Args:
        category_names (Iterable[str]): The names of the file's categories

    Returns:
        dict[str, Any]: The section - texts empty, lists empty, `order` None
    """
    return {
        BestPracticeMetaKey.TITLE.value: '',
        BestPracticeMetaKey.BADGE.value: '',
        BestPracticeMetaKey.SUMMARY.value: '',
        BestPracticeMetaKey.DESCRIPTION.value: '',
        BestPracticeMetaKey.SUITED_FOR.value: [],
        BestPracticeMetaKey.PROFILES.value: [],
        BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value: {name: '' for name in category_names},
        BestPracticeMetaKey.ORDER.value: None,
    }


def build_transfer_file(
        db_version: int,
        components: dict[str, dict[str, Any]],
        exported_at: datetime | None = None,
        *,
        name: str,
        description: str = '') -> dict[str, Any]:
    """
    Builds a transfer file around the sections of its components

    Args:
        db_version (int): The updater version of the exporting database
        components (dict[str, dict[str, Any]]): Each component's section, keyed by its name
        exported_at (datetime | None): The export time; None stamps the current UTC time
        name (str): What the exporting user calls the file
        description (str): The exporting user's description of it - empty when none was given

    Returns:
        dict[str, Any]: The transfer file - `information` filled in, `meta` empty
    """
    stamp: datetime = exported_at or datetime.now(timezone.utc)

    return {
        TransferFileKey.FORMAT_VERSION.value: TRANSFER_FORMAT_VERSION,
        TransferFileKey.DB_VERSION.value: db_version,
        TransferFileKey.EXPORTED_AT.value: stamp.isoformat(),
        TransferFileKey.INFORMATION.value: build_information(name, description, components),
        TransferFileKey.META.value: build_empty_meta(category_names_of(components)),
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
        return [FILE_KEY_NOT_AN_OBJECT.format(key=TransferFileKey.COMPONENTS.value)]

    names: list[str] = list(component_names)
    problems: list[str] = [MISSING_COMPONENT.format(name=name) for name in names if name not in components]
    problems += [UNKNOWN_COMPONENT.format(name=name) for name in sorted(components) if name not in names]

    for name in names:
        if name in components:
            problems += find_section_problems(name, components[name])

    return problems


def information_text_problems(information: dict[str, Any], key: TransferInformationKey, blank_allowed: bool,
                              max_length: int | None) -> list[str]:
    """
    Judges one text of a file's `information` - a missing key is `find_key_problems`' to name

    Args:
        information (dict[str, Any]): The stored `information`
        key (TransferInformationKey): The text's key
        blank_allowed (bool): Whether an empty or blank string passes
        max_length (int | None): The longest the text may be; None for no limit

    Returns:
        list[str]: The problems, empty when the text is usable or absent
    """
    if key.value not in information:
        return []

    value: Any = information[key.value]
    context: dict[str, str] = {'section': TransferFileKey.INFORMATION.value, 'key': key.value}

    if not isinstance(value, str):
        return [INFORMATION_NOT_A_STRING.format(**context)]

    if not blank_allowed and not is_non_blank_string(value):
        return [INFORMATION_NOT_TEXT.format(**context)]

    if max_length is not None and len(value) > max_length:
        return [INFORMATION_TOO_LONG.format(max_length=max_length, **context)]

    return []


def stored_item_count(components: Any, name: str) -> int | None:
    """
    Answers how many entries a component's section holds, when that can be read

    Args:
        components (Any): The stored `components`
        name (str): The component's name

    Returns:
        int | None: The number of entries, or None when the section or its `items` is not usable - its own rules
                    name that problem
    """
    section: Any = components.get(name) if isinstance(components, dict) else None
    items: Any = section.get(TransferSectionKey.ITEMS.value) if isinstance(section, dict) else None

    return len(items) if isinstance(items, list) else None


def find_counts_problems(counts: Any, components: Any, component_names: Iterable[str]) -> list[str]:
    """
    Judges a file's `information` counts: one whole number per registered component, each matching its entries

    Args:
        counts (Any): The stored counts
        components (Any): The stored `components`
        component_names (Iterable[str]): The registered components' names

    Returns:
        list[str]: The problems, empty when every count is usable and matches
    """
    section: str = TransferFileKey.INFORMATION.value

    if not isinstance(counts, dict):
        return [FILE_KEY_NOT_AN_OBJECT.format(key=f'{section}.{TransferInformationKey.COUNTS.value}')]

    names: list[str] = list(component_names)
    problems: list[str] = find_key_problems(counts, names, MISSING_COUNT, UNKNOWN_COUNT, section=section)

    for name in names:
        if name not in counts:
            continue

        count: Any = counts[name]

        if not (is_strict_int(count) and count >= 0):
            problems.append(COUNT_NOT_A_NUMBER.format(section=section, name=name))
            continue

        actual: int | None = stored_item_count(components, name)

        if actual is not None and actual != count:
            problems.append(COUNT_MISMATCH.format(section=section, name=name, count=count, actual=actual))

    return problems


def find_information_problems(information: Any, components: Any, component_names: Iterable[str]) -> list[str]:
    """
    Judges a file's `information`: its keys, its texts, and counts that match the entries

    Args:
        information (Any): The stored `information`
        components (Any): The stored `components`
        component_names (Iterable[str]): The registered components' names

    Returns:
        list[str]: The problems, empty when the section is usable
    """
    if not isinstance(information, dict):
        return [FILE_KEY_NOT_AN_OBJECT.format(key=TransferFileKey.INFORMATION.value)]

    problems: list[str] = find_key_problems(information, [key.value for key in TransferInformationKey],
                                            MISSING_SECTION_FIELD, UNKNOWN_SECTION_FIELD,
                                            section=TransferFileKey.INFORMATION.value)
    problems += information_text_problems(information, TransferInformationKey.NAME, False,
                                          INFORMATION_NAME_MAX_LENGTH)
    problems += information_text_problems(information, TransferInformationKey.DESCRIPTION, True,
                                          INFORMATION_DESCRIPTION_MAX_LENGTH)
    problems += information_text_problems(information, TransferInformationKey.VERSION, False, None)

    if TransferInformationKey.COUNTS.value in information:
        problems += find_counts_problems(information[TransferInformationKey.COUNTS.value], components,
                                         component_names)

    return problems


def readable_information(data: Any, component_names: Iterable[str]) -> dict[str, Any] | None:
    """
    Answers a file's `information` when it can be shown as it is - whatever else the file holds

    Args:
        data (Any): The parsed upload
        component_names (Iterable[str]): The registered components' names

    Returns:
        dict[str, Any] | None: The section, or None when the file has none or it has a problem of its own
    """
    if not isinstance(data, dict) or TransferFileKey.INFORMATION.value not in data:
        return None

    information: Any = data[TransferFileKey.INFORMATION.value]
    problems: list[str] = find_information_problems(information, data.get(TransferFileKey.COMPONENTS.value),
                                                    component_names)

    return None if problems else information


def find_meta_problems(meta: Any) -> list[str]:
    """
    Judges a file's `meta`: every key present, nothing else, each value of its kind - empty values pass

    Whether a best-practice model's `meta` is filled in is the catalogue's to judge, with the strict schema

    Args:
        meta (Any): The stored `meta`

    Returns:
        list[str]: The problems, empty when the section is usable
    """
    key: str = TransferFileKey.META.value

    if not isinstance(meta, dict):
        return [FILE_KEY_NOT_AN_OBJECT.format(key=key)]

    validator = Validator(get_exported_meta_schema())

    if validator.validate(meta):
        return []

    return [META_INVALID.format(key=key, errors=validator.errors)]


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

    if TransferFileKey.INFORMATION.value in data:
        problems += find_information_problems(data[TransferFileKey.INFORMATION.value],
                                              data.get(TransferFileKey.COMPONENTS.value), component_names)

    if TransferFileKey.META.value in data:
        problems += find_meta_problems(data[TransferFileKey.META.value])

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
