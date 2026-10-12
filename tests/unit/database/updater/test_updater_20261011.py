# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.database.updater.versions.updater_20261011

The migration strips the stored user and group names the name rule refuses, where stripping alone repairs them and
the stripped name is free, and logs the rest. Its run against real collections is its own integration test; this
module owns the frozen literals and rule, the per-document decisions, and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261011 as module
from cmdb.database.updater.versions.updater_20261011 import Update20261011, is_clean_name, repaired_name
from cmdb.errors.database import DocumentGetError, DocumentUpdateDuplicateKeyError, DocumentUpdateError
from cmdb.errors.updater import UpdaterException
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.utils import CONTROL_CHARACTER_CATEGORY, name_shape_problem
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261011
DATABASE_NAME: str = 'cmdb-unit'
USERS: str = CmdbUser.COLLECTION
GROUPS: str = CmdbUserGroup.COLLECTION
USER_NAME: str = CmdbUserKey.USER_NAME.value
PADDED_ID: int = 4
TAKEN_ID: int = 5

# Stored names and what the rule makes of each
SAMPLE_NAMES: list[Any] = ['bob', ' bob ', '\u00a0bob', '', '   ', 'a\tb', ' a\tb ', 'a b', None, 7]


def _build_stubbed_updater(documents: dict[str, list[dict[str, Any]]], taken: bool = False) -> Any:
    """The updater with a stubbed database manager answering each collection's documents"""
    updater = Update20261011.__new__(Update20261011)
    updater.dbm = MagicMock()
    updater.dbm.find.side_effect = lambda collection, **_kwargs: iter(documents.get(collection, []))
    updater.dbm.count.return_value = 1 if taken else 0
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


@pytest.mark.parametrize('frozen, live', [
    (module.USER_COLLECTION, CmdbUser.COLLECTION),
    (module.USER_NAME_FIELD, CmdbUserKey.USER_NAME.value),
    (module.GROUP_COLLECTION, CmdbUserGroup.COLLECTION),
    (module.GROUP_NAME_FIELD, GroupKey.NAME.value),
    (module.PUBLIC_ID_FIELD, CmdbUserKey.PUBLIC_ID.value),
    (module.CONTROL_CHARACTER_CATEGORY, CONTROL_CHARACTER_CATEGORY),
], ids=['users', 'user-name', 'groups', 'group-name', 'public-id', 'control-category'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


@pytest.mark.parametrize('name', SAMPLE_NAMES)
def test_the_frozen_rule_agrees_with_the_live_one_when_it_shipped(name: Any) -> None:
    """A clean name is exactly one the write rule accepts"""
    assert is_clean_name(name) == (isinstance(name, str) and name_shape_problem(name) is None)


@pytest.mark.parametrize('name, expected', [
    (' bob ', 'bob'), ('\u00a0bob', 'bob'), ('', None), ('   ', None), (' a\tb ', None), (None, None), (7, None),
], ids=['padded', 'unicode-padded', 'empty', 'blank', 'control-inside', 'none', 'integer'])
def test_only_what_stripping_makes_clean_is_repaired(name: Any, expected: str | None) -> None:
    """A blank name or a control character inside is left for an administrator"""
    assert repaired_name(name) == expected


def test_both_collections_are_read_projected_to_their_name() -> None:
    """One read per collection, the name and the public_id only"""
    updater = _build_stubbed_updater({})

    updater.start_update()

    reads: list[tuple[str, dict[str, Any]]] = [
        (call.kwargs['collection'], call.kwargs['projection']) for call in updater.dbm.find.call_args_list
    ]
    assert reads == [
        (USERS, {'public_id': 1, 'user_name': 1, '_id': 0}),
        (GROUPS, {'public_id': 1, 'name': 1, '_id': 0}),
    ]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_padded_name_is_stripped_on_the_condition_of_the_name_read() -> None:
    """A name changed since the read is left alone"""
    updater = _build_stubbed_updater({USERS: [{'public_id': PADDED_ID, USER_NAME: ' bob '}]})

    updater.start_update()

    updater.dbm.update.assert_called_once_with(
        USERS, DATABASE_NAME, {'public_id': PADDED_ID, USER_NAME: ' bob '}, {USER_NAME: 'bob'})
    updater.dbm.count.assert_called_once_with(USERS, DATABASE_NAME, {USER_NAME: 'bob'}, limit=1)


def test_a_clean_name_is_not_touched() -> None:
    """Nothing to repair, nothing asked"""
    updater = _build_stubbed_updater({USERS: [{'public_id': PADDED_ID, USER_NAME: 'bob'}]})

    updater.start_update()

    updater.dbm.count.assert_not_called()
    updater.dbm.update.assert_not_called()


def test_a_taken_stripped_name_is_logged_and_left(caplog: pytest.LogCaptureFixture) -> None:
    """The pre-read finds the clash"""
    updater = _build_stubbed_updater({GROUPS: [{'public_id': TAKEN_ID, 'name': ' ops '}]}, taken=True)

    updater.start_update()

    updater.dbm.update.assert_not_called()
    assert GROUPS in caplog.text and str(TAKEN_ID) in caplog.text and 'taken' in caplog.text
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_clash_only_the_index_catches_is_logged_and_left(caplog: pytest.LogCaptureFixture) -> None:
    """A concurrent write took the name between the count and the update"""
    updater = _build_stubbed_updater({USERS: [{'public_id': TAKEN_ID, USER_NAME: 'bob '}]})
    updater.dbm.update.side_effect = DocumentUpdateDuplicateKeyError('dup', key_pattern={}, key_value={})

    updater.start_update()

    assert str(TAKEN_ID) in caplog.text and 'taken' in caplog.text
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


@pytest.mark.parametrize('name', ['', '   ', 'a\tb', None], ids=['empty', 'blank', 'control', 'none'])
def test_an_unrepairable_name_is_logged_and_left(name: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Nothing is written; the log names the document"""
    updater = _build_stubbed_updater({USERS: [{'public_id': PADDED_ID, USER_NAME: name}]})

    updater.start_update()

    updater.dbm.count.assert_not_called()
    updater.dbm.update.assert_not_called()
    assert USERS in caplog.text and str(PADDED_ID) in caplog.text and 'rename' in caplog.text


@pytest.mark.parametrize('failing, error', [
    ('find', DocumentGetError('down')),
    ('count', DocumentGetError('down')),
    ('update', DocumentUpdateError('down')),
], ids=['read', 'count', 'write'])
def test_a_failed_step_is_wrapped_with_the_error_itself_and_leaves_the_version(failing: str,
                                                                                error: Exception) -> None:
    """The next start runs the whole migration again"""
    updater = _build_stubbed_updater({USERS: [{'public_id': PADDED_ID, USER_NAME: ' bob '}]})
    getattr(updater.dbm, failing).side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error
    assert exc_info.value.args[0] is error
    updater.increase_updater_version.assert_not_called()


def test_the_description_names_the_names() -> None:
    """The line the updater log prints"""
    assert 'names' in Update20261011.__new__(Update20261011).description()
