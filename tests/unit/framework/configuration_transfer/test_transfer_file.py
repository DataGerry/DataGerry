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
Unit tests for cmdb.framework.configuration_transfer.transfer_file

Pure tests: no Mongo, no Flask. What is pinned here: a built file carries the envelope this code reads (so an
export always passes its own envelope check), every envelope rule reports its problem instead of raising and the
checks collect every problem of a file at once, numbers are strict JSON integers (a bool, a float or a numeric
string is refused), every registered component must be present and nothing else may be, and the version check
passes an exact match only
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.configuration_transfer import (
    TRANSFER_FORMAT_VERSION,
    TransferFileKey,
    TransferSectionKey,
    build_component_section,
    build_transfer_file,
    db_version_mismatch,
    db_version_too_new,
    find_transfer_file_problems,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
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
from cmdb.framework.configuration_transfer.transfer_file import (
    db_version_problem,
    exported_at_problem,
    find_components_problems,
    find_key_problems,
    find_section_problems,
    format_version_problem,
    is_strict_int,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_COMPONENT: str = 'alpha'
SECOND_COMPONENT: str = 'beta'
STRAY_COMPONENT: str = 'gamma'
COMPONENT_NAMES: list[str] = [FIRST_COMPONENT, SECOND_COMPONENT]

FILE_DB_VERSION: int = 20261014
OTHER_DB_VERSION: int = 20261013
FIRST_COUNTER: int = 17
SECOND_COUNTER: int = 4
FIRST_ITEMS: list[dict[str, Any]] = [{'public_id': 3}, {'public_id': 9}]
SECOND_ITEMS: list[dict[str, Any]] = [{'public_id': 2}]
EXPORT_TIME: datetime = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
STRAY_KEY: str = 'stray'

FORMAT_KEY: str = TransferFileKey.FORMAT_VERSION.value
DB_KEY: str = TransferFileKey.DB_VERSION.value
EXPORTED_KEY: str = TransferFileKey.EXPORTED_AT.value
COMPONENTS_KEY: str = TransferFileKey.COMPONENTS.value
COUNTER_KEY: str = TransferSectionKey.COUNTER.value
ITEMS_KEY: str = TransferSectionKey.ITEMS.value


def _valid_file() -> dict[str, Any]:
    """A file whose envelope passes, with distinct values per component"""
    return build_transfer_file(FILE_DB_VERSION, {
        FIRST_COMPONENT: build_component_section(FIRST_COUNTER, list(FIRST_ITEMS)),
        SECOND_COMPONENT: build_component_section(SECOND_COUNTER, list(SECOND_ITEMS)),
    }, EXPORT_TIME)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       builders                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_build_component_section_keeps_counter_and_items_apart() -> None:
    """The counter and the items land under their own keys"""
    assert build_component_section(FIRST_COUNTER, FIRST_ITEMS) == {COUNTER_KEY: FIRST_COUNTER, ITEMS_KEY: FIRST_ITEMS}


def test_build_transfer_file_writes_the_envelope() -> None:
    """Format version, db version, ISO stamp and the components are written as given"""
    components: dict[str, Any] = {FIRST_COMPONENT: build_component_section(FIRST_COUNTER, FIRST_ITEMS)}

    assert build_transfer_file(FILE_DB_VERSION, components, EXPORT_TIME) == {
        FORMAT_KEY: TRANSFER_FORMAT_VERSION,
        DB_KEY: FILE_DB_VERSION,
        EXPORTED_KEY: EXPORT_TIME.isoformat(),
        COMPONENTS_KEY: components,
    }


def test_build_transfer_file_stamps_now_in_utc_without_a_time() -> None:
    """No export time given -> the current UTC time, as an aware ISO string"""
    before: datetime = datetime.now(timezone.utc)
    stamp: datetime = datetime.fromisoformat(build_transfer_file(FILE_DB_VERSION, {})[EXPORTED_KEY])

    assert stamp.tzinfo is not None
    assert before <= stamp <= datetime.now(timezone.utc)


def test_a_built_file_passes_its_own_envelope_check() -> None:
    """What an export writes, an import's envelope check accepts"""
    assert not find_transfer_file_problems(_valid_file(), COMPONENT_NAMES)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      value rules                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value,expected', [
    (0, True), (FILE_DB_VERSION, True), (-1, True),
    (True, False), (False, False), (1.0, False), ('1', False), (None, False),
])
def test_is_strict_int(value: Any, expected: bool) -> None:
    """Only an int that is not a bool counts"""
    assert is_strict_int(value) is expected


def test_format_version_problem_passes_the_current_version_only() -> None:
    """The version this code writes passes; any other value, a bool or a string names the expected version"""
    expected: str = FORMAT_VERSION_MISMATCH.format(key=FORMAT_KEY, expected=TRANSFER_FORMAT_VERSION)

    assert format_version_problem(TRANSFER_FORMAT_VERSION) is None

    for value in (TRANSFER_FORMAT_VERSION + 1, str(TRANSFER_FORMAT_VERSION), True, None):
        assert format_version_problem(value) == expected


def test_db_version_problem_wants_a_positive_whole_number() -> None:
    """A positive int passes; zero, a negative, a float, a string and a bool do not"""
    expected: str = DB_VERSION_NOT_A_NUMBER.format(key=DB_KEY)

    assert db_version_problem(FILE_DB_VERSION) is None

    for value in (0, -FILE_DB_VERSION, float(FILE_DB_VERSION), str(FILE_DB_VERSION), True):
        assert db_version_problem(value) == expected


def test_exported_at_problem_wants_a_non_blank_string() -> None:
    """Any non-blank string passes - nothing is derived from the stamp"""
    expected: str = EXPORTED_AT_NOT_A_STRING.format(key=EXPORTED_KEY)

    assert exported_at_problem(EXPORT_TIME.isoformat()) is None

    for value in ('', '   ', None, FILE_DB_VERSION):
        assert exported_at_problem(value) == expected


def test_db_version_mismatch_passes_an_exact_match_only() -> None:
    """Same version -> None; an older or newer one names both versions"""
    assert db_version_mismatch(FILE_DB_VERSION, FILE_DB_VERSION) is None

    assert db_version_mismatch(OTHER_DB_VERSION, FILE_DB_VERSION) == DB_VERSION_MISMATCH.format(
        file_version=OTHER_DB_VERSION, target_version=FILE_DB_VERSION
    )
    assert db_version_mismatch(FILE_DB_VERSION, OTHER_DB_VERSION) == DB_VERSION_MISMATCH.format(
        file_version=FILE_DB_VERSION, target_version=OTHER_DB_VERSION
    )

def test_db_version_too_new_refuses_a_newer_file_only() -> None:
    """Same or older -> None (an older file is migrated); newer names both versions"""
    assert db_version_too_new(FILE_DB_VERSION, FILE_DB_VERSION) is None
    assert db_version_too_new(OTHER_DB_VERSION, FILE_DB_VERSION) is None
    assert db_version_too_new(FILE_DB_VERSION, OTHER_DB_VERSION) == DB_VERSION_TOO_NEW.format(
        file_version=FILE_DB_VERSION, target_version=OTHER_DB_VERSION
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       key rule                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_find_key_problems_names_missing_then_unknown_keys() -> None:
    """Missing keys in expected order first, unknown keys sorted after, context passed to the templates"""
    template_missing: str = '{name}: no {key}'
    template_unknown: str = '{name}: stray {key}'
    document: dict[str, Any] = {'z': 1, 'b': 2, 'y': 3}

    assert find_key_problems(document, ['c', 'b', 'a'], template_missing, template_unknown, name=FIRST_COMPONENT) == [
        f'{FIRST_COMPONENT}: no c',
        f'{FIRST_COMPONENT}: no a',
        f'{FIRST_COMPONENT}: stray y',
        f'{FIRST_COMPONENT}: stray z',
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     section rule                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_find_section_problems_accepts_an_empty_section() -> None:
    """A component with nothing to transfer is a section with no items and counter 0"""
    assert not find_section_problems(FIRST_COMPONENT, build_component_section(0, []))


@pytest.mark.parametrize('section', [None, [], 'section', FIRST_COUNTER])
def test_find_section_problems_refuses_a_non_object(section: Any) -> None:
    """A section that is not an object is one problem and nothing else is asked of it"""
    assert find_section_problems(FIRST_COMPONENT, section) == [SECTION_NOT_AN_OBJECT.format(name=FIRST_COMPONENT)]


def test_find_section_problems_names_missing_and_unknown_keys() -> None:
    """No counter, no items, a stray key -> three problems naming the component"""
    assert find_section_problems(SECOND_COMPONENT, {STRAY_KEY: 1}) == [
        MISSING_SECTION_KEY.format(name=SECOND_COMPONENT, key=COUNTER_KEY),
        MISSING_SECTION_KEY.format(name=SECOND_COMPONENT, key=ITEMS_KEY),
        UNKNOWN_SECTION_KEY.format(name=SECOND_COMPONENT, key=STRAY_KEY),
    ]


@pytest.mark.parametrize('counter', [-1, True, 1.5, float(FIRST_COUNTER), str(FIRST_COUNTER), None])
def test_find_section_problems_refuses_a_counter_that_is_no_whole_number(counter: Any) -> None:
    """A negative, a bool, a float or a string counter is refused"""
    assert find_section_problems(FIRST_COMPONENT, build_component_section(counter, [])) == [
        COUNTER_NOT_A_NUMBER.format(name=FIRST_COMPONENT, key=COUNTER_KEY)
    ]


@pytest.mark.parametrize('items', [None, {}, 'items', FIRST_COUNTER])
def test_find_section_problems_refuses_items_that_are_no_list(items: Any) -> None:
    """Items that are not a list are one problem"""
    assert find_section_problems(FIRST_COMPONENT, {COUNTER_KEY: FIRST_COUNTER, ITEMS_KEY: items}) == [
        ITEMS_NOT_A_LIST.format(name=FIRST_COMPONENT, key=ITEMS_KEY)
    ]


def test_find_section_problems_names_every_item_that_is_no_object() -> None:
    """Each non-object entry is named by its index; the object entries pass"""
    items: list[Any] = [{'public_id': 1}, None, {'public_id': 2}, 'x']

    assert find_section_problems(FIRST_COMPONENT, build_component_section(FIRST_COUNTER, items)) == [
        ITEM_NOT_AN_OBJECT.format(index=1, name=FIRST_COMPONENT),
        ITEM_NOT_AN_OBJECT.format(index=3, name=FIRST_COMPONENT),
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   components rule                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('components', [None, [], 'components'])
def test_find_components_problems_refuses_a_non_object(components: Any) -> None:
    """Components that are not an object are one problem"""
    assert find_components_problems(components, COMPONENT_NAMES) == [
        COMPONENTS_NOT_AN_OBJECT.format(key=COMPONENTS_KEY)
    ]


def test_find_components_problems_names_missing_and_unknown_components() -> None:
    """A registered component absent and an unregistered one present are both named"""
    components: dict[str, Any] = {
        FIRST_COMPONENT: build_component_section(FIRST_COUNTER, []),
        STRAY_COMPONENT: build_component_section(SECOND_COUNTER, []),
    }

    assert find_components_problems(components, COMPONENT_NAMES) == [
        MISSING_COMPONENT.format(name=SECOND_COMPONENT),
        UNKNOWN_COMPONENT.format(name=STRAY_COMPONENT),
    ]


def test_find_components_problems_judges_each_present_section() -> None:
    """Each registered section is judged under its own name"""
    components: dict[str, Any] = {FIRST_COMPONENT: None, SECOND_COMPONENT: build_component_section(-1, [])}

    assert find_components_problems(components, COMPONENT_NAMES) == [
        SECTION_NOT_AN_OBJECT.format(name=FIRST_COMPONENT),
        COUNTER_NOT_A_NUMBER.format(name=SECOND_COMPONENT, key=COUNTER_KEY),
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     whole file                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('data', [None, [], 'file', FILE_DB_VERSION])
def test_find_transfer_file_problems_refuses_a_non_object(data: Any) -> None:
    """A file that is not an object stops at that one problem"""
    assert find_transfer_file_problems(data, COMPONENT_NAMES) == [FILE_NOT_AN_OBJECT]


def test_find_transfer_file_problems_names_missing_and_unknown_keys() -> None:
    """An empty object lacks every key; a stray key is named after them"""
    assert find_transfer_file_problems({STRAY_KEY: 1}, COMPONENT_NAMES) == [
        MISSING_FILE_KEY.format(key=FORMAT_KEY),
        MISSING_FILE_KEY.format(key=DB_KEY),
        MISSING_FILE_KEY.format(key=EXPORTED_KEY),
        MISSING_FILE_KEY.format(key=COMPONENTS_KEY),
        UNKNOWN_FILE_KEY.format(key=STRAY_KEY),
    ]


def test_find_transfer_file_problems_collects_every_problem_at_once() -> None:
    """Bad version, bad db version, bad stamp and a bad section are all reported together, in that order"""
    data: dict[str, Any] = _valid_file()
    data[FORMAT_KEY] = TRANSFER_FORMAT_VERSION + 1
    data[DB_KEY] = str(FILE_DB_VERSION)
    data[EXPORTED_KEY] = ''
    data[COMPONENTS_KEY][SECOND_COMPONENT][ITEMS_KEY] = None

    assert find_transfer_file_problems(data, COMPONENT_NAMES) == [
        FORMAT_VERSION_MISMATCH.format(key=FORMAT_KEY, expected=TRANSFER_FORMAT_VERSION),
        DB_VERSION_NOT_A_NUMBER.format(key=DB_KEY),
        EXPORTED_AT_NOT_A_STRING.format(key=EXPORTED_KEY),
        ITEMS_NOT_A_LIST.format(name=SECOND_COMPONENT, key=ITEMS_KEY),
    ]
