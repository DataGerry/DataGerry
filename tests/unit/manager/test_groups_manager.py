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
Unit tests for cmdb.manager.groups_manager.GroupsManager

Pure tests: no Mongo. The override methods (``insert_group``, ``get_group``, ``update_group``,
``delete_group``) and the rights-cache init are exercised against a MagicMock standing in for the
manager instance. The one-line delegation ``iterate`` is intentionally outside the scope - it is
covered transitively by the GenericManager unit suite and the integration tests in
tests/integration/management
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.groups_manager import GroupsManager, PROTECTED_GROUP_IDS
from cmdb.models.group_model import CmdbUserGroup

from cmdb.errors.manager.groups_manager import (
    GroupsManagerInitError,
    GroupsManagerInsertError,
    GroupsManagerGetError,
    GroupsManagerDeleteError,
)
from cmdb.errors.models.cmdb_user_group import CmdbUserGroupToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.manager.groups_manager'

NEW_GROUP_PUBLIC_ID: int = 17
MISSING_GROUP_PUBLIC_ID: int = 9999
REGULAR_GROUP_PUBLIC_ID: int = 5
ADMIN_GROUP_PUBLIC_ID: int = PROTECTED_GROUP_IDS[0]
USER_GROUP_PUBLIC_ID: int = PROTECTED_GROUP_IDS[1]

SAMPLE_GROUP_DICT: dict[str, Any] = {'public_id': NEW_GROUP_PUBLIC_ID, 'name': 'g', 'label': 'G', 'rights': []}
SERIALIZED_GROUP_DICT: dict[str, Any] = {'public_id': NEW_GROUP_PUBLIC_ID, 'name': 'g', 'label': 'G', 'rights': ['r']}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a GroupsManager, with a cached rights sentinel."""
    mgr = MagicMock(spec=GroupsManager)
    mgr.rights = MagicMock(name='cached_rights_tree')
    return mgr


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       __init__                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """``GroupsManager.__init__`` wires the GenericManager base and caches the rights tree."""

    def test_caches_flat_rights_tree(self) -> None:
        """After construction ``self.rights`` is the value returned by ``flat_rights_tree``."""
        sentinel_rights = MagicMock(name='rights')

        with patch.object(GenericManager, '__init__', return_value=None), \
             patch(f'{MODULE_PATH}.flat_rights_tree', return_value=sentinel_rights):
            mgr = GroupsManager(dbm=MagicMock())

        assert mgr.rights is sentinel_rights

    def test_wraps_rights_cache_failure_as_init_error(self) -> None:
        """If ``flat_rights_tree`` raises, the wrapper surfaces it as ``GroupsManagerInitError``."""
        with patch.object(GenericManager, '__init__', return_value=None), \
             patch(f'{MODULE_PATH}.flat_rights_tree', side_effect=RuntimeError('boom')):
            with pytest.raises(GroupsManagerInitError):
                GroupsManager(dbm=MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      insert_group                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertGroup:
    """``insert_group`` serializes model instances with ``insert_mode=True`` and delegates to insert."""

    def test_dict_is_passed_through_to_insert(self) -> None:
        """A dict input is handed to ``self.insert`` unchanged; the returned public_id is returned."""
        mgr = _mock_manager()
        mgr.insert.return_value = NEW_GROUP_PUBLIC_ID

        result = GroupsManager.insert_group(mgr, SAMPLE_GROUP_DICT)

        assert result == NEW_GROUP_PUBLIC_ID
        mgr.insert.assert_called_once_with(SAMPLE_GROUP_DICT)

    def test_model_instance_is_serialised_with_insert_mode_true(self) -> None:
        """A ``CmdbUserGroup`` instance is serialised via ``to_json(group, True)`` before insert."""
        mgr = _mock_manager()
        mgr.insert.return_value = NEW_GROUP_PUBLIC_ID
        instance = MagicMock(spec=CmdbUserGroup)

        with patch.object(CmdbUserGroup, 'to_json', return_value=SERIALIZED_GROUP_DICT) as to_json_mock:
            result = GroupsManager.insert_group(mgr, instance)

        to_json_mock.assert_called_once_with(instance, True)
        mgr.insert.assert_called_once_with(SERIALIZED_GROUP_DICT)
        assert result == NEW_GROUP_PUBLIC_ID

    def test_tojson_error_wraps_as_insert_error(self) -> None:
        """A ``CmdbUserGroupToJsonError`` is surfaced as ``GroupsManagerInsertError``."""
        mgr = _mock_manager()
        instance = MagicMock(spec=CmdbUserGroup)

        with patch.object(CmdbUserGroup, 'to_json', side_effect=CmdbUserGroupToJsonError('bad')):
            with pytest.raises(GroupsManagerInsertError):
                GroupsManager.insert_group(mgr, instance)

    def test_unexpected_error_wraps_as_insert_error(self) -> None:
        """A generic exception from the insert path is wrapped as ``GroupsManagerInsertError``."""
        mgr = _mock_manager()
        mgr.insert.side_effect = RuntimeError('db down')

        with pytest.raises(GroupsManagerInsertError):
            GroupsManager.insert_group(mgr, SAMPLE_GROUP_DICT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       get_group                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetGroup:
    """``get_group`` returns a hydrated ``CmdbUserGroup`` or None, surfacing failures as Get errors."""

    def test_returns_cmdb_user_group_hydrated_with_cached_rights(self) -> None:
        """A present id (fetched via ``get_item``) is rehydrated via ``from_data(data, self.rights)``."""
        mgr = _mock_manager()
        mgr.get_item.return_value = SAMPLE_GROUP_DICT
        sentinel_group = MagicMock(spec=CmdbUserGroup)

        with patch.object(CmdbUserGroup, 'from_data', return_value=sentinel_group) as from_data_mock:
            result = GroupsManager.get_group(mgr, NEW_GROUP_PUBLIC_ID)

        mgr.get_item.assert_called_once_with(NEW_GROUP_PUBLIC_ID, as_dict=True)
        from_data_mock.assert_called_once_with(SAMPLE_GROUP_DICT, mgr.rights)
        assert result is sentinel_group

    def test_returns_none_when_id_not_present(self) -> None:
        """A missing id returns None without invoking ``from_data``."""
        mgr = _mock_manager()
        mgr.get_item.return_value = None

        with patch.object(CmdbUserGroup, 'from_data') as from_data_mock:
            result = GroupsManager.get_group(mgr, MISSING_GROUP_PUBLIC_ID)

        assert result is None
        from_data_mock.assert_not_called()

    def test_from_data_failure_wraps_as_get_error(self) -> None:
        """A failure while rehydrating the fetched document is wrapped as ``GroupsManagerGetError``."""
        mgr = _mock_manager()
        mgr.get_item.return_value = SAMPLE_GROUP_DICT

        with patch.object(CmdbUserGroup, 'from_data', side_effect=RuntimeError('bad rights')):
            with pytest.raises(GroupsManagerGetError):
                GroupsManager.get_group(mgr, NEW_GROUP_PUBLIC_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   is_protected_group                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsProtectedGroup:
    """``is_protected_group`` reports membership in ``PROTECTED_GROUP_IDS``."""

    @pytest.mark.parametrize('protected_id', [ADMIN_GROUP_PUBLIC_ID, USER_GROUP_PUBLIC_ID])
    def test_bootstrap_ids_are_protected(self, protected_id: int) -> None:
        """The bootstrap admin / user group ids are reported as protected."""
        assert GroupsManager.is_protected_group(_mock_manager(), protected_id) is True

    def test_regular_id_is_not_protected(self) -> None:
        """A regular group id is not protected."""
        assert GroupsManager.is_protected_group(_mock_manager(), REGULAR_GROUP_PUBLIC_ID) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      hydrate_group                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHydrateGroup:
    """``hydrate_group`` resolves rights via the cached tree and serializes with insert_mode=True."""

    def test_hydrates_via_cached_rights_and_insert_mode(self) -> None:
        """from_data is fed ``self.rights``; the result is serialized via ``to_json(group, True)``."""
        mgr = _mock_manager()
        sentinel_group = MagicMock(spec=CmdbUserGroup)

        with patch.object(CmdbUserGroup, 'from_data', return_value=sentinel_group) as from_data_mock, \
             patch.object(CmdbUserGroup, 'to_json', return_value=SERIALIZED_GROUP_DICT) as to_json_mock:
            result = GroupsManager.hydrate_group(mgr, SAMPLE_GROUP_DICT)

        from_data_mock.assert_called_once_with(SAMPLE_GROUP_DICT, mgr.rights)
        to_json_mock.assert_called_once_with(sentinel_group, True)
        assert result is SERIALIZED_GROUP_DICT


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      update_group                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateGroup:
    """``update_group`` serializes models insert-mode, pins the identity, and delegates to update_item."""

    def test_dict_pins_public_id_to_the_arg_and_delegates(self) -> None:
        """A payload public_id is overwritten with the arg before the update is delegated."""
        mgr = _mock_manager()
        payload: dict[str, Any] = {'public_id': 999, 'name': 'g', 'rights': []}  # wrong/forged id

        GroupsManager.update_group(mgr, NEW_GROUP_PUBLIC_ID, payload)

        assert payload['public_id'] == NEW_GROUP_PUBLIC_ID
        mgr.update_item.assert_called_once_with(NEW_GROUP_PUBLIC_ID, payload)

    def test_model_is_serialised_insert_mode_then_pinned(self) -> None:
        """A model is serialized via ``to_json(group, True)`` and the result's identity is pinned."""
        mgr = _mock_manager()
        instance = MagicMock(spec=CmdbUserGroup)
        serialized: dict[str, Any] = {'public_id': 999, 'name': 'g', 'rights': ['r']}

        with patch.object(CmdbUserGroup, 'to_json', return_value=serialized) as to_json_mock:
            GroupsManager.update_group(mgr, NEW_GROUP_PUBLIC_ID, instance)

        to_json_mock.assert_called_once_with(instance, True)
        assert serialized['public_id'] == NEW_GROUP_PUBLIC_ID
        mgr.update_item.assert_called_once_with(NEW_GROUP_PUBLIC_ID, serialized)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      delete_group                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteGroup:
    """``delete_group`` refuses protected groups and otherwise delegates to ``GenericManager.delete_item``."""

    def test_protected_group_raises_delete_error(self) -> None:
        """When ``is_protected_group`` is True the delete raises without touching the storage layer."""
        mgr = _mock_manager()
        mgr.is_protected_group.return_value = True

        with pytest.raises(GroupsManagerDeleteError):
            GroupsManager.delete_group(mgr, ADMIN_GROUP_PUBLIC_ID)

        mgr.delete_item.assert_not_called()

    def test_unprotected_id_delegates_to_delete_item(self) -> None:
        """A non-protected id is delegated to ``delete_item`` and its bool return is returned."""
        mgr = _mock_manager()
        mgr.is_protected_group.return_value = False
        mgr.delete_item.return_value = True

        result = GroupsManager.delete_group(mgr, REGULAR_GROUP_PUBLIC_ID)

        mgr.delete_item.assert_called_once_with(REGULAR_GROUP_PUBLIC_ID)
        assert result is True
