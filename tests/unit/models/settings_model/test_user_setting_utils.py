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
Unit tests for cmdb.models.settings_model.user_setting_utils

The read side of the settings collection, which sees documents this version of DataGerry did not
necessarily write. Until 2026-09-09 reading them was strict and fatal: one unresolvable `setting_type`
failed the whole list read for that user, and the frontend - which syncs settings on login and only
logs a failure - then silently stopped restoring any of them.

What is pinned here: the answer shape, every coercion (a numeric string user_id, an absent or null
payload list), the values that are REFUSED (a bool user_id, a scope outside the enum), and that an
unreadable document answers None with a log line naming its resource rather than raising.
"""
from typing import Any

import pytest

from cmdb.models.settings_model.user_setting_constants import UserSettingKey
from cmdb.models.settings_model.user_setting_type_enum import UserSettingType
from cmdb.models.settings_model.user_setting_utils import (
    coerce_payloads,
    coerce_setting_type,
    coerce_user_id,
    normalize_user_setting_document,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 42
RESOURCE: str = 'dashboard'
PAYLOADS: list[dict[str, Any]] = [{'id': 'table-1', 'columns': ['public_id', 'name']}]


def _document(**overrides: Any) -> dict[str, Any]:
    """A stored CmdbUserSetting document."""
    document: dict[str, Any] = {
        UserSettingKey.RESOURCE.value: RESOURCE,
        UserSettingKey.USER_ID.value: USER_ID,
        UserSettingKey.PAYLOADS.value: PAYLOADS,
        UserSettingKey.SETTING_TYPE.value: UserSettingType.APPLICATION.value,
        UserSettingKey.PUBLIC_ID.value: 7,
    }
    document.update(overrides)

    return document


# -------------------------------------------------------------------------------------------------------------------- #
#                                              coerce_setting_type                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCoerceSettingType:
    """The one place the stored string and the enum member meet."""

    def test_a_member_is_returned_unchanged(self) -> None:
        """A caller holding a member should not have to know how it is stored"""
        assert coerce_setting_type(UserSettingType.GLOBAL) is UserSettingType.GLOBAL

    @pytest.mark.parametrize('value', ['GLOBAL', 'APPLICATION', 'SERVER'])
    def test_each_stored_value_resolves(self, value: str) -> None:
        """The three values are what the schema allows and what the collection holds"""
        assert coerce_setting_type(value).value == value

    @pytest.mark.parametrize('value', ['NOT_A_TYPE', '', None, 1], ids=['unknown', 'empty', 'none', 'int'])
    def test_anything_else_is_refused(self, value: Any) -> None:
        """
        The refusal that used to happen on the read path and cost the whole list

        It is now also refused at the door: the document schema allows exactly the three values.
        """
        with pytest.raises(ValueError):
            coerce_setting_type(value)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                coerce_user_id                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCoerceUserId:
    """The owner's public_id, which used to be read with a bare int()."""

    def test_an_int_passes(self) -> None:
        """The normal case"""
        assert coerce_user_id(USER_ID) == USER_ID

    def test_a_numeric_string_is_coerced(self) -> None:
        """What the old bare `int()` accepted, kept deliberately"""
        assert coerce_user_id('42') == 42

    @pytest.mark.parametrize('value', [None, 'abc', 3.5, [], {}],
                             ids=['none', 'text', 'float', 'list', 'dict'])
    def test_anything_unusable_is_refused_as_a_value_error(self, value: Any) -> None:
        """A bare int() raised TypeError for None and ValueError for text - one error type now"""
        with pytest.raises(ValueError):
            coerce_user_id(value)

    @pytest.mark.parametrize('value', [True, False], ids=['true', 'false'])
    def test_a_bool_is_refused(self, value: bool) -> None:
        """`int(True)` is 1, which would silently claim the settings of user 1"""
        with pytest.raises(ValueError):
            coerce_user_id(value)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                coerce_payloads                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCoercePayloads:
    """What a setting actually stores - and the one thing no test ever exercised before."""

    def test_the_entries_are_handed_back_as_stored(self) -> None:
        """They are the client's own structures; the backend attaches no meaning to them"""
        assert coerce_payloads(PAYLOADS) == PAYLOADS

    def test_none_becomes_an_empty_list(self) -> None:
        """A stored null and a missing key are the same statement: nothing stored yet"""
        assert coerce_payloads(None) == []

    @pytest.mark.parametrize('value', ['nope', 5, {'id': 1}], ids=['text', 'int', 'dict'])
    def test_anything_but_a_list_is_refused(self, value: Any) -> None:
        """A non-list would be iterated as one somewhere downstream"""
        with pytest.raises(ValueError):
            coerce_payloads(value)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       normalize_user_setting_document                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestNormalizeUserSettingDocument:
    """One stored document in the shape the list route answers."""

    def test_the_answer_carries_exactly_the_four_keys(self) -> None:
        """`public_id` is stamped in the collection but is not part of this shape (backlog #218)"""
        answered = normalize_user_setting_document(_document())

        assert answered == {
            UserSettingKey.RESOURCE.value: RESOURCE,
            UserSettingKey.USER_ID.value: USER_ID,
            UserSettingKey.PAYLOADS.value: PAYLOADS,
            UserSettingKey.SETTING_TYPE.value: UserSettingType.APPLICATION.value,
        }

    def test_a_missing_payload_list_is_reported_as_empty(self) -> None:
        """The key is optional, and a client reads `payloads` unconditionally"""
        document = _document()
        del document[UserSettingKey.PAYLOADS.value]

        assert normalize_user_setting_document(document)[UserSettingKey.PAYLOADS.value] == []

    def test_a_stored_null_payload_list_is_reported_as_empty(self) -> None:
        """The write path refuses null today; a legacy document is never re-validated"""
        assert normalize_user_setting_document(
            _document(**{UserSettingKey.PAYLOADS.value: None}),
        )[UserSettingKey.PAYLOADS.value] == []

    def test_a_numeric_string_user_id_is_answered_as_an_int(self) -> None:
        """Whatever is stored, the answer is typed as the frontend model expects it"""
        assert normalize_user_setting_document(
            _document(**{UserSettingKey.USER_ID.value: '42'}),
        )[UserSettingKey.USER_ID.value] == USER_ID

    @pytest.mark.parametrize('overrides, reason', [
        ({UserSettingKey.SETTING_TYPE.value: 'NOT_A_TYPE'}, 'an unknown scope'),
        ({UserSettingKey.USER_ID.value: None}, 'no user_id'),
        ({UserSettingKey.PAYLOADS.value: 'nope'}, 'a payload list that is not a list'),
    ], ids=['bad-scope', 'no-user-id', 'bad-payloads'])
    def test_an_unreadable_document_answers_none(self, overrides: dict[str, Any], reason: str) -> None:
        """
        Each of these used to fail the WHOLE list read for that user

        The caller skips the record instead, so the user's other settings still load. `reason` names
        what is wrong with the document for the test id.
        """
        assert normalize_user_setting_document(_document(**overrides)) is None, reason

    def test_a_document_without_a_resource_answers_none(self) -> None:
        """Its identity is (user_id, resource); without one it cannot be addressed at all"""
        document = _document()
        del document[UserSettingKey.RESOURCE.value]

        assert normalize_user_setting_document(document) is None

    def test_the_skipped_document_is_logged_with_its_resource(self, caplog) -> None:
        """The resource is the only handle an administrator has for finding the bad record"""
        with caplog.at_level('WARNING'):
            normalize_user_setting_document(_document(**{UserSettingKey.SETTING_TYPE.value: 'NOT_A_TYPE'}))

        assert RESOURCE in caplog.text
        assert 'Skipping an unreadable UserSetting' in caplog.text

    def test_nothing_is_raised_for_an_empty_document(self) -> None:
        """The read may not depend on what a document happens to carry"""
        assert normalize_user_setting_document({}) is None
