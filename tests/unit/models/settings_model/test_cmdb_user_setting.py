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
Unit tests for cmdb.models.settings_model.cmdb_user_setting

The write path's model: the routes hand it a validated body, and it is the one place a setting's
values are normalised. It had **no test module of its own** until 2026-09-09 - what little of it ran
did so through the manager's integration tests, which is why its three `except` arms were uncovered
and its `payloads` never held anything.

What is pinned here: the round trip (including a NON-EMPTY payload list, which no test in the
repository used to store), the normalisation the constructor performs, the refusals, the typed errors
each entry point raises, and that `to_json` refuses a foreign instance - the guard the ISMS models
needed after two structurally identical entities serialised as each other.
"""
from typing import Any

import pytest
from pymongo import IndexModel

from cmdb.models.settings_model.cmdb_user_setting import CmdbUserSetting
from cmdb.models.settings_model.user_setting_constants import UserSettingKey
from cmdb.models.settings_model.user_setting_type_enum import UserSettingType

from cmdb.errors.models.cmdb_user_setting import (
    CmdbUserSettingInitError,
    CmdbUserSettingInitFromDataError,
    CmdbUserSettingToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 42
RESOURCE: str = 'dashboard'
# What the Angular table service really stores: one entry per table, keyed by its own id
PAYLOADS: list[dict[str, Any]] = [
    {'id': 'objects-table', 'columns': ['public_id', 'name'], 'page_size': 25},
]


def _data(**overrides: Any) -> dict[str, Any]:
    """A request body as the routes hand it to from_data."""
    data: dict[str, Any] = {
        UserSettingKey.RESOURCE.value: RESOURCE,
        UserSettingKey.USER_ID.value: USER_ID,
        UserSettingKey.PAYLOADS.value: PAYLOADS,
        UserSettingKey.SETTING_TYPE.value: UserSettingType.APPLICATION.value,
    }
    data.update(overrides)

    return data


def _setting(**overrides: Any) -> CmdbUserSetting:
    """A CmdbUserSetting built from a request body."""
    return CmdbUserSetting.from_data(_data(**overrides))


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the constructor                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """The one place a setting's values are normalised."""

    def test_the_values_are_stored_as_given(self) -> None:
        """Nothing is invented and nothing is dropped"""
        setting = CmdbUserSetting(RESOURCE, USER_ID, PAYLOADS, UserSettingType.GLOBAL)

        assert setting.resource == RESOURCE
        assert setting.user_id == USER_ID
        assert setting.payloads == PAYLOADS
        assert setting.setting_type is UserSettingType.GLOBAL

    def test_a_stored_scope_string_becomes_a_member(self) -> None:
        """So `to_json` can always read `.value` - it used to break with AttributeError instead"""
        assert CmdbUserSetting(RESOURCE, USER_ID, [], 'SERVER').setting_type is UserSettingType.SERVER

    def test_an_absent_payload_list_becomes_empty(self) -> None:
        """A setting with nothing stored yet is a normal state"""
        assert CmdbUserSetting(RESOURCE, USER_ID, None, UserSettingType.GLOBAL).payloads == []

    def test_a_numeric_string_user_id_is_coerced(self) -> None:
        """What the old bare `int()` in from_data accepted"""
        assert CmdbUserSetting(RESOURCE, '42', [], UserSettingType.GLOBAL).user_id == USER_ID

    @pytest.mark.parametrize('setting_type', ['NOT_A_TYPE', None, 7], ids=['unknown', 'none', 'int'])
    def test_an_unknown_scope_is_refused(self, setting_type: Any) -> None:
        """Refused at construction rather than stored and tripped over on the next read"""
        with pytest.raises(CmdbUserSettingInitError):
            CmdbUserSetting(RESOURCE, USER_ID, [], setting_type)

    @pytest.mark.parametrize('user_id', [None, 'abc', True], ids=['none', 'text', 'bool'])
    def test_an_unusable_user_id_is_refused(self, user_id: Any) -> None:
        """A bool would silently claim user 1's settings"""
        with pytest.raises(CmdbUserSettingInitError):
            CmdbUserSetting(RESOURCE, user_id, [], UserSettingType.GLOBAL)

    def test_a_payload_list_that_is_not_a_list_is_refused(self) -> None:
        """It would be iterated as one downstream"""
        with pytest.raises(CmdbUserSettingInitError):
            CmdbUserSetting(RESOURCE, USER_ID, 'nope', UserSettingType.GLOBAL)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  from_data                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFromData:
    """The write path's entry point."""

    def test_a_request_body_becomes_a_setting(self) -> None:
        """What both write routes hand it after schema validation"""
        setting = _setting()

        assert setting.resource == RESOURCE
        assert setting.payloads == PAYLOADS
        assert setting.setting_type is UserSettingType.APPLICATION

    def test_the_public_id_is_not_read(self) -> None:
        """It is not part of the model, which is why an update `$set`s the four keys and leaves it"""
        setting = _setting(**{UserSettingKey.PUBLIC_ID.value: 99})

        assert not hasattr(setting, UserSettingKey.PUBLIC_ID.value)

    def test_a_missing_resource_is_refused(self) -> None:
        """Read with [] on purpose: without a resource the setting has no identity"""
        data = _data()
        del data[UserSettingKey.RESOURCE.value]

        with pytest.raises(CmdbUserSettingInitFromDataError):
            CmdbUserSetting.from_data(data)

    @pytest.mark.parametrize('overrides', [
        {UserSettingKey.SETTING_TYPE.value: 'NOT_A_TYPE'},
        {UserSettingKey.USER_ID.value: None},
        {UserSettingKey.PAYLOADS.value: 'nope'},
    ], ids=['bad-scope', 'no-user-id', 'bad-payloads'])
    def test_an_unusable_body_raises_the_models_own_error(self, overrides: dict[str, Any]) -> None:
        """The route maps this to a refusal; a bare TypeError would have surfaced as a 500"""
        with pytest.raises(CmdbUserSettingInitFromDataError):
            CmdbUserSetting.from_data(_data(**overrides))

    def test_an_empty_body_raises_rather_than_building_a_hollow_setting(self) -> None:
        """Nothing here is optional except the payload list"""
        with pytest.raises(CmdbUserSettingInitFromDataError):
            CmdbUserSetting.from_data({})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   to_json                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestToJson:
    """What the update path writes back."""

    def test_the_four_keys_are_answered(self) -> None:
        """`public_id` is deliberately absent: the model does not own it"""
        assert CmdbUserSetting.to_json(_setting()) == {
            UserSettingKey.RESOURCE.value: RESOURCE,
            UserSettingKey.USER_ID.value: USER_ID,
            UserSettingKey.PAYLOADS.value: PAYLOADS,
            UserSettingKey.SETTING_TYPE.value: UserSettingType.APPLICATION.value,
        }

    def test_the_scope_is_answered_as_its_stored_value(self) -> None:
        """A member would not survive the BSON write"""
        assert isinstance(
            CmdbUserSetting.to_json(_setting())[UserSettingKey.SETTING_TYPE.value], str,
        )

    def test_the_payload_entries_travel_unchanged(self) -> None:
        """
        The round trip that nothing exercised before 2026-09-09

        Every fixture in the repository stored `payloads: []`, so the wrapper class that used to sit
        here - a dict in, the same dict out - never ran at all. It was removed; these entries are the
        client's own structures and the backend attaches no meaning to them.
        """
        answered = CmdbUserSetting.to_json(CmdbUserSetting.from_data(_data()))

        assert answered[UserSettingKey.PAYLOADS.value] == PAYLOADS
        assert answered[UserSettingKey.PAYLOADS.value][0]['columns'] == ['public_id', 'name']

    def test_a_foreign_instance_is_refused(self) -> None:
        """The guard the ISMS models needed: two same-shaped models serialised as each other"""
        class _Impostor:  # pylint: disable=too-few-public-methods
            """Carries the very same attribute names"""
            resource = RESOURCE
            user_id = USER_ID
            payloads: list[dict[str, Any]] = []
            setting_type = UserSettingType.GLOBAL

        with pytest.raises(CmdbUserSettingToJsonError):
            CmdbUserSetting.to_json(_Impostor())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the index                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIndexKeys:
    """Its identity is enforced by the database, not by the model."""

    def test_the_compound_index_is_declared_unique(self) -> None:
        """(resource, user_id) is what makes one setting per user and resource a guarantee"""
        indexes: list[IndexModel] = CmdbUserSetting.get_index_keys()

        assert len(indexes) == 1
        document = indexes[0].document
        assert document['unique'] is True
        assert list(document['key']) == [UserSettingKey.RESOURCE.value, UserSettingKey.USER_ID.value]

    def test_the_collection_is_the_user_management_one(self) -> None:
        """Registered in user_management_constants.__COLLECTIONS__, which is what builds the index"""
        assert CmdbUserSetting.COLLECTION == 'management.users.settings'
