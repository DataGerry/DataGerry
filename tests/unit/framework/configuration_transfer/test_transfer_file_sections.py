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
Unit tests for the `information` and `meta` sections of a transfer file (``transfer_file``)

Pure tests: no Mongo, no Flask. What is pinned here: what an export writes into both sections (the user's name and
description, the release, the entries per component; an empty meta naming every category), what an uploaded file's
sections may hold - each problem named, counts that do not match their entries refused, an empty meta accepted - and
when a file's `information` is shown as it is
"""
from typing import Any

import pytest

from cmdb import __version__
from cmdb.framework.configuration_transfer.best_practice_constants import BestPracticeMetaKey
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    INFORMATION_DESCRIPTION_MAX_LENGTH,
    INFORMATION_NAME_MAX_LENGTH,
    TransferComponentName,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
    COUNT_MISMATCH,
    COUNT_NOT_A_NUMBER,
    FILE_KEY_NOT_AN_OBJECT,
    INFORMATION_NOT_A_STRING,
    INFORMATION_NOT_TEXT,
    INFORMATION_TOO_LONG,
    META_INVALID,
    MISSING_COUNT,
    MISSING_FILE_KEY,
    MISSING_SECTION_FIELD,
    UNKNOWN_COUNT,
    UNKNOWN_SECTION_FIELD,
)
from cmdb.framework.configuration_transfer.transfer_file import (
    build_component_section,
    build_empty_meta,
    build_information,
    build_transfer_file,
    category_names_of,
    count_component_items,
    find_counts_problems,
    find_information_problems,
    find_meta_problems,
    find_transfer_file_problems,
    readable_information,
    stored_item_count,
)
from cmdb.models.category_model.category_constants import CategoryKey
# -------------------------------------------------------------------------------------------------------------------- #

EXPORT_NAME: str = 'Contacts'
EXPORT_DESCRIPTION: str = 'Companies and the people working for them'
DB_VERSION: int = 20261021
CATEGORIES: str = TransferComponentName.CATEGORIES.value
TYPES: str = TransferComponentName.TYPES.value
COMPONENT_NAMES: list[str] = [TYPES, CATEGORIES]
STRAY_COMPONENT: str = 'gamma'
FIRST_CATEGORY: str = 'contacts'
SECOND_CATEGORY: str = 'locations'
TYPE_ITEMS: list[dict[str, Any]] = [{'public_id': 3}, {'public_id': 7}, {'public_id': 9}]
CATEGORY_ITEMS: list[dict[str, Any]] = [{CategoryKey.NAME.value: FIRST_CATEGORY},
                                        {CategoryKey.NAME.value: SECOND_CATEGORY}]
STRAY_KEY: str = 'stray'

INFORMATION: str = TransferFileKey.INFORMATION.value
META: str = TransferFileKey.META.value
NAME: str = TransferInformationKey.NAME.value
DESCRIPTION: str = TransferInformationKey.DESCRIPTION.value
VERSION: str = TransferInformationKey.VERSION.value
COUNTS: str = TransferInformationKey.COUNTS.value
ITEMS: str = TransferSectionKey.ITEMS.value


def _components() -> dict[str, dict[str, Any]]:
    """Three types and two categories - distinct counts, so a swapped count shows"""
    return {
        TYPES: build_component_section(9, list(TYPE_ITEMS)),
        CATEGORIES: build_component_section(2, list(CATEGORY_ITEMS)),
    }


def _information(**changes: Any) -> dict[str, Any]:
    """A usable `information` for `_components`, with `changes` applied"""
    return {**build_information(EXPORT_NAME, EXPORT_DESCRIPTION, _components()), **changes}


def _file() -> dict[str, Any]:
    """A usable transfer file of `_components`"""
    return build_transfer_file(DB_VERSION, _components(), name=EXPORT_NAME, description=EXPORT_DESCRIPTION)


def _section_context(key: str) -> dict[str, str]:
    """What a message about one `information` key is formatted with"""
    return {'section': INFORMATION, 'key': key}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       builders                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_count_component_items_counts_each_sections_entries() -> None:
    """One count per component, in section order"""
    assert list(count_component_items(_components()).items()) == [(TYPES, len(TYPE_ITEMS)),
                                                                  (CATEGORIES, len(CATEGORY_ITEMS))]


def test_category_names_of_reads_the_names_in_entry_order() -> None:
    """Every category's name"""
    assert category_names_of(_components()) == [FIRST_CATEGORY, SECOND_CATEGORY]


@pytest.mark.parametrize('components', [
    {},
    {CATEGORIES: build_component_section(0, [{CategoryKey.NAME.value: ' '}, {CategoryKey.NAME.value: 4}, {}])},
], ids=['no-categories', 'unusable-names'])
def test_category_names_of_skips_what_is_no_name(components: dict[str, Any]) -> None:
    """No section, a blank, a number or no name at all - none of them is named"""
    assert not category_names_of(components)


def test_build_information_carries_the_users_texts_the_release_and_the_counts() -> None:
    """Distinct values per key, so a swapped key shows"""
    assert build_information(EXPORT_NAME, EXPORT_DESCRIPTION, _components()) == {
        NAME: EXPORT_NAME,
        DESCRIPTION: EXPORT_DESCRIPTION,
        VERSION: __version__,
        COUNTS: {TYPES: len(TYPE_ITEMS), CATEGORIES: len(CATEGORY_ITEMS)},
    }


def test_build_empty_meta_leaves_every_value_empty_and_names_every_category() -> None:
    """Texts '', lists [], order None; one empty description per category"""
    assert build_empty_meta([FIRST_CATEGORY, SECOND_CATEGORY]) == {
        BestPracticeMetaKey.TITLE.value: '',
        BestPracticeMetaKey.BADGE.value: '',
        BestPracticeMetaKey.SUMMARY.value: '',
        BestPracticeMetaKey.DESCRIPTION.value: '',
        BestPracticeMetaKey.SUITED_FOR.value: [],
        BestPracticeMetaKey.PROFILES.value: [],
        BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value: {FIRST_CATEGORY: '', SECOND_CATEGORY: ''},
        BestPracticeMetaKey.ORDER.value: None,
    }


def test_build_transfer_file_writes_both_sections() -> None:
    """The information of its components and an empty meta naming its categories"""
    transfer_file: dict[str, Any] = _file()

    assert transfer_file[INFORMATION] == _information()
    assert transfer_file[META] == build_empty_meta([FIRST_CATEGORY, SECOND_CATEGORY])


def test_build_transfer_file_defaults_the_description_to_empty() -> None:
    """No description given -> ''"""
    assert build_transfer_file(DB_VERSION, _components(), name=EXPORT_NAME)[INFORMATION][DESCRIPTION] == ''


def test_a_built_file_passes_its_own_check() -> None:
    """What an export writes, an import accepts - an empty meta included"""
    assert not find_transfer_file_problems(_file(), COMPONENT_NAMES)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     information                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('information', [None, [], 'text'], ids=['null', 'list', 'text'])
def test_information_that_is_no_object_is_refused(information: Any) -> None:
    """Named by its key"""
    assert find_information_problems(information, _components(), COMPONENT_NAMES) == [
        FILE_KEY_NOT_AN_OBJECT.format(key=INFORMATION),
    ]


def test_information_names_missing_and_unknown_keys() -> None:
    """Missing ones first, in key order, then the unknown"""
    assert find_information_problems({STRAY_KEY: 1}, _components(), COMPONENT_NAMES) == [
        *[MISSING_SECTION_FIELD.format(**_section_context(key.value)) for key in TransferInformationKey],
        UNKNOWN_SECTION_FIELD.format(**_section_context(STRAY_KEY)),
    ]


@pytest.mark.parametrize('key,value,message', [
    (NAME, 7, INFORMATION_NOT_A_STRING),
    (NAME, '', INFORMATION_NOT_TEXT),
    (NAME, ' \n ', INFORMATION_NOT_TEXT),
    (DESCRIPTION, None, INFORMATION_NOT_A_STRING),
    (VERSION, ' ', INFORMATION_NOT_TEXT),
    (VERSION, 340, INFORMATION_NOT_A_STRING),
], ids=['name-number', 'name-empty', 'name-blank', 'description-null', 'version-blank', 'version-number'])
def test_an_unusable_text_is_named(key: str, value: Any, message: str) -> None:
    """One problem naming the key"""
    assert find_information_problems(_information(**{key: value}), _components(), COMPONENT_NAMES) == [
        message.format(**_section_context(key)),
    ]


@pytest.mark.parametrize('key,max_length', [(NAME, INFORMATION_NAME_MAX_LENGTH),
                                            (DESCRIPTION, INFORMATION_DESCRIPTION_MAX_LENGTH)])
def test_a_text_may_reach_its_limit_but_not_pass_it(key: str, max_length: int) -> None:
    """At the limit passes; one more character is named with the limit"""
    assert not find_information_problems(_information(**{key: 'x' * max_length}), _components(), COMPONENT_NAMES)
    assert find_information_problems(_information(**{key: 'x' * (max_length + 1)}), _components(),
                                     COMPONENT_NAMES) == [
        INFORMATION_TOO_LONG.format(max_length=max_length, **_section_context(key)),
    ]


def test_an_empty_description_passes() -> None:
    """The user may give none"""
    assert not find_information_problems(_information(**{DESCRIPTION: ''}), _components(), COMPONENT_NAMES)


def test_counts_that_are_no_object_are_refused() -> None:
    """Named by their path"""
    assert find_counts_problems([1, 2], _components(), COMPONENT_NAMES) == [
        FILE_KEY_NOT_AN_OBJECT.format(key=f'{INFORMATION}.{COUNTS}'),
    ]


def test_counts_name_missing_and_unknown_components() -> None:
    """The missing component, then the stray one"""
    counts: dict[str, Any] = {TYPES: len(TYPE_ITEMS), STRAY_COMPONENT: 1}

    assert find_counts_problems(counts, _components(), COMPONENT_NAMES) == [
        MISSING_COUNT.format(section=INFORMATION, key=CATEGORIES),
        UNKNOWN_COUNT.format(section=INFORMATION, key=STRAY_COMPONENT),
    ]


@pytest.mark.parametrize('count', [-1, 1.0, '3', True, None], ids=['negative', 'float', 'text', 'boolean', 'null'])
def test_a_count_that_is_no_whole_number_is_named(count: Any) -> None:
    """And not compared with the entries"""
    counts: dict[str, Any] = {TYPES: count, CATEGORIES: len(CATEGORY_ITEMS)}

    assert find_counts_problems(counts, _components(), COMPONENT_NAMES) == [
        COUNT_NOT_A_NUMBER.format(section=INFORMATION, name=TYPES),
    ]


def test_a_count_that_does_not_match_its_entries_is_named() -> None:
    """Each mismatching component with both numbers - the matching one is not named"""
    counts: dict[str, Any] = {TYPES: len(TYPE_ITEMS) + 1, CATEGORIES: len(CATEGORY_ITEMS)}

    assert find_counts_problems(counts, _components(), COMPONENT_NAMES) == [
        COUNT_MISMATCH.format(section=INFORMATION, name=TYPES, count=len(TYPE_ITEMS) + 1, actual=len(TYPE_ITEMS)),
    ]


@pytest.mark.parametrize('components', [
    None,
    {TYPES: 'no section'},
    {TYPES: {ITEMS: 'no list'}},
], ids=['no-components', 'no-section', 'no-items-list'])
def test_a_count_whose_entries_cannot_be_read_is_not_compared(components: Any) -> None:
    """The section's own rules name that problem - the count adds none"""
    assert stored_item_count(components, TYPES) is None
    assert not find_counts_problems({TYPES: 99, CATEGORIES: 0}, components, COMPONENT_NAMES)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                         meta                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_an_exported_meta_passes() -> None:
    """Every value empty, order None"""
    assert not find_meta_problems(build_empty_meta([FIRST_CATEGORY]))


@pytest.mark.parametrize('meta', [None, [], 'meta'], ids=['null', 'list', 'text'])
def test_a_meta_that_is_no_object_is_refused(meta: Any) -> None:
    """Named by its key"""
    assert find_meta_problems(meta) == [FILE_KEY_NOT_AN_OBJECT.format(key=META)]


@pytest.mark.parametrize('change,key', [
    ({STRAY_KEY: ''}, STRAY_KEY),
    ({BestPracticeMetaKey.TITLE.value: None}, BestPracticeMetaKey.TITLE.value),
    ({BestPracticeMetaKey.SUITED_FOR.value: ''}, BestPracticeMetaKey.SUITED_FOR.value),
    ({BestPracticeMetaKey.PROFILES.value: [3]}, BestPracticeMetaKey.PROFILES.value),
    ({BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value: []}, BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value),
    ({BestPracticeMetaKey.ORDER.value: True}, BestPracticeMetaKey.ORDER.value),
    ({BestPracticeMetaKey.ORDER.value: -1}, BestPracticeMetaKey.ORDER.value),
], ids=['unknown-key', 'title-null', 'list-text', 'list-of-numbers', 'descriptions-list', 'order-boolean',
        'order-negative'])
def test_a_meta_value_of_the_wrong_kind_is_named(change: dict[str, Any], key: str) -> None:
    """One problem, naming the key - the kind is held although the values may be empty"""
    problems: list[str] = find_meta_problems({**build_empty_meta([]), **change})

    assert len(problems) == 1
    assert problems[0].startswith(META_INVALID.split('{errors}', maxsplit=1)[0].format(key=META))
    assert key in problems[0]


def test_a_missing_meta_key_is_named() -> None:
    """Every key is required"""
    meta: dict[str, Any] = build_empty_meta([])
    del meta[BestPracticeMetaKey.BADGE.value]

    assert BestPracticeMetaKey.BADGE.value in find_meta_problems(meta)[0]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the whole envelope                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_file_without_the_sections_names_both() -> None:
    """Both keys are required"""
    transfer_file: dict[str, Any] = _file()
    del transfer_file[INFORMATION], transfer_file[META]

    assert find_transfer_file_problems(transfer_file, COMPONENT_NAMES) == [
        MISSING_FILE_KEY.format(key=INFORMATION), MISSING_FILE_KEY.format(key=META),
    ]


def test_the_sections_problems_come_after_the_components() -> None:
    """Components, then information, then meta - every problem at once"""
    transfer_file: dict[str, Any] = _file()
    transfer_file[TransferFileKey.COMPONENTS.value][STRAY_COMPONENT] = build_component_section(0, [])
    transfer_file[INFORMATION][NAME] = ''
    transfer_file[META] = []

    problems: list[str] = find_transfer_file_problems(transfer_file, COMPONENT_NAMES)

    assert problems[1:] == [INFORMATION_NOT_TEXT.format(**_section_context(NAME)),
                            FILE_KEY_NOT_AN_OBJECT.format(key=META)]
    assert STRAY_COMPONENT in problems[0]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 readable information                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_readable_information_answers_a_usable_section_as_it_is() -> None:
    """The stored section itself"""
    transfer_file: dict[str, Any] = _file()

    assert readable_information(transfer_file, COMPONENT_NAMES) is transfer_file[INFORMATION]


def test_readable_information_ignores_problems_elsewhere_in_the_file() -> None:
    """A broken meta does not hide the information"""
    transfer_file: dict[str, Any] = {**_file(), META: 'broken'}

    assert readable_information(transfer_file, COMPONENT_NAMES) == _information()


@pytest.mark.parametrize('transfer_file', [
    [],
    {},
    {INFORMATION: 'text'},
    {INFORMATION: {NAME: EXPORT_NAME}},
], ids=['no-object', 'no-information', 'information-no-object', 'information-incomplete'])
def test_readable_information_is_none_for_an_unusable_section(transfer_file: Any) -> None:
    """Nothing half-read is shown"""
    assert readable_information(transfer_file, COMPONENT_NAMES) is None


def test_readable_information_is_none_when_the_counts_do_not_match() -> None:
    """The counts would show what the file does not hold"""
    transfer_file: dict[str, Any] = _file()
    transfer_file[INFORMATION][COUNTS][TYPES] += 1

    assert readable_information(transfer_file, COMPONENT_NAMES) is None
