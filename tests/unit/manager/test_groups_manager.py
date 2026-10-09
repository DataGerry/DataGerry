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

Pure tests: no Mongo. The override methods (``insert_group``, ``get_group``, ``iterate``,
``update_group``, ``delete_group``), the model builder ``_build_group`` and the rights-cache init are
exercised against a MagicMock standing in for the manager instance. ``iterate`` is no delegation: the
generic ``iterate_items`` builds groups without the right tree, so the override is pinned here - every
row built with ``self.rights``, a failure wrapped as ``GroupsManagerIterationError``
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.groups_manager import GroupsManager, PROTECTED_GROUP_IDS
from cmdb.models.group_model import CmdbUserGroup, MASTER_RIGHT_NAME
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.groups_manager import (
    GroupsManagerInitError,
    GroupsManagerInsertError,
    GroupsManagerGetError,
    GroupsManagerIterationError,
    GroupsManagerDeleteError,
)
from cmdb.errors.models.cmdb_user_group import CmdbUserGroupToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.manager.groups_manager'

NEW_GROUP_PUBLIC_ID: int = 17
MISSING_GROUP_PUBLIC_ID: int = 9999
REGULAR_GROUP_PUBLIC_ID: int = 5
QUERY_TOTAL: int = 12
ADMIN_GROUP_PUBLIC_ID: int = PROTECTED_GROUP_IDS[0]
USER_GROUP_PUBLIC_ID: int = PROTECTED_GROUP_IDS[1]

SAMPLE_GROUP_DICT: dict[str, Any] = {'public_id': NEW_GROUP_PUBLIC_ID, 'name': 'g', 'label': 'G', 'rights': []}
SERIALIZED_GROUP_DICT: dict[str, Any] = {'public_id': NEW_GROUP_PUBLIC_ID, 'name': 'g', 'label': 'G', 'rights': ['r']}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a GroupsManager, with a cached rights sentinel."""
    mgr = MagicMock(spec=GroupsManager)
    mgr.rights = MagicMock(name='cached_rights_tree')
    # The real model builder, so every read the tests drive goes through the one place rights are resolved
    mgr._build_group = lambda document: GroupsManager._build_group(mgr, document)
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

    def test_caches_every_right_name(self) -> None:
        """``self.right_names`` is the set of names of the cached tree."""
        with patch.object(GenericManager, '__init__', return_value=None):
            mgr = GroupsManager(dbm=MagicMock())

        assert mgr.right_names == frozenset(right.name for right in mgr.rights)
        assert MASTER_RIGHT_NAME in mgr.right_names

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

    @pytest.mark.parametrize('failure', [
        DocumentNetworkError('connection lost'),
        DocumentLockTimeoutError('lock timeout'),
    ], ids=['network', 'lock-timeout'])
    def test_a_transient_failure_is_raised_unwrapped(self, failure: Exception) -> None:
        """Not the insert error the route answers 400: a lock timeout or an outage is no fault of the group."""
        mgr = _mock_manager()
        mgr.insert.side_effect = failure

        with pytest.raises(type(failure)) as caught:
            GroupsManager.insert_group(mgr, SAMPLE_GROUP_DICT)

        assert caught.value is failure


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
#                                                  _build_group / iterate                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildGroup:
    """``_build_group`` is ``from_data`` fed the cached right tree."""

    def test_feeds_the_cached_tree(self) -> None:
        """The document and ``self.rights`` go to ``from_data``; its group is returned."""
        mgr = _mock_manager()
        sentinel_group = MagicMock(spec=CmdbUserGroup)

        with patch.object(CmdbUserGroup, 'from_data', return_value=sentinel_group) as from_data_mock:
            result = GroupsManager._build_group(mgr, SAMPLE_GROUP_DICT)

        from_data_mock.assert_called_once_with(SAMPLE_GROUP_DICT, mgr.rights)
        assert result is sentinel_group

    def test_resolves_stored_names_against_the_real_tree(self) -> None:
        """Against the real tree a stored name comes back as the right, not as nothing."""
        mgr = _mock_manager()
        mgr.rights = flat_rights_tree(ALL_RIGHTS)

        group = GroupsManager._build_group(mgr, {**SAMPLE_GROUP_DICT, 'rights': [MASTER_RIGHT_NAME]})

        assert [right.name for right in group.rights] == [MASTER_RIGHT_NAME]


class TestIterate:
    """``iterate`` runs the generic query and builds every row with the right tree."""

    def test_every_row_is_built_with_the_tree_and_the_total_is_kept(self) -> None:
        """Each document goes through ``_build_group``; the count is the query's total."""
        mgr = _mock_manager()
        other_document: dict[str, Any] = {**SAMPLE_GROUP_DICT, 'public_id': REGULAR_GROUP_PUBLIC_ID}
        mgr.iterate_query.return_value = ([SAMPLE_GROUP_DICT, other_document], QUERY_TOTAL)
        built: list[MagicMock] = [MagicMock(spec=CmdbUserGroup), MagicMock(spec=CmdbUserGroup)]
        params = MagicMock(name='builder_params')

        with patch.object(CmdbUserGroup, 'from_data', side_effect=built) as from_data_mock:
            result = GroupsManager.iterate(mgr, params)

        mgr.iterate_query.assert_called_once_with(params)
        assert from_data_mock.call_args_list == [
            ((SAMPLE_GROUP_DICT, mgr.rights),), ((other_document, mgr.rights),),
        ]
        assert result.results == built
        assert result.total == QUERY_TOTAL
        assert result.count == len(built)

    def test_rows_carry_their_resolved_rights(self) -> None:
        """Against the real tree the listed group holds its rights - the defect was an empty list here."""
        mgr = _mock_manager()
        mgr.rights = flat_rights_tree(ALL_RIGHTS)
        mgr.iterate_query.return_value = ([{**SAMPLE_GROUP_DICT, 'rights': [MASTER_RIGHT_NAME]}], 1)

        result = GroupsManager.iterate(mgr, MagicMock(name='builder_params'))

        assert [right.name for right in result.results[0].rights] == [MASTER_RIGHT_NAME]

    def test_an_empty_page_is_an_empty_result(self) -> None:
        """No documents, no models; the total is still the query's."""
        mgr = _mock_manager()
        mgr.iterate_query.return_value = ([], QUERY_TOTAL)

        result = GroupsManager.iterate(mgr, MagicMock(name='builder_params'))

        assert not result.results
        assert result.total == QUERY_TOTAL

    @pytest.mark.parametrize('failing', ['query', 'row'])
    def test_a_failure_is_wrapped_as_iteration_error_carrying_it(self, failing: str) -> None:
        """A failed query or an unreadable row is a ``GroupsManagerIterationError`` holding the error itself."""
        mgr = _mock_manager()
        failure = RuntimeError('down')

        if failing == 'query':
            mgr.iterate_query.side_effect = failure
        else:
            mgr.iterate_query.return_value = ([SAMPLE_GROUP_DICT], 1)

        with patch.object(CmdbUserGroup, 'from_data', side_effect=failure):
            with pytest.raises(GroupsManagerIterationError) as exc_info:
                GroupsManager.iterate(mgr, MagicMock(name='builder_params'))

        assert exc_info.value.args[0] is failure
        assert exc_info.value.__cause__ is failure


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      hydrate_group                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHydrateGroup:
    """``hydrate_group`` builds the model an update writes, its rights resolved through the cached tree."""

    def test_builds_the_model_from_the_cached_rights(self) -> None:
        """from_data is fed ``self.rights`` and the model itself is returned - nothing is serialised here."""
        mgr = _mock_manager()
        sentinel_group = MagicMock(spec=CmdbUserGroup)

        with patch.object(CmdbUserGroup, 'from_data', return_value=sentinel_group) as from_data_mock, \
             patch.object(CmdbUserGroup, 'to_json') as to_json_mock:
            result = GroupsManager.hydrate_group(mgr, SAMPLE_GROUP_DICT)

        from_data_mock.assert_called_once_with(SAMPLE_GROUP_DICT, mgr.rights)
        to_json_mock.assert_not_called()
        assert result is sentinel_group

    def test_rights_are_held_once_each_in_tree_order(self) -> None:
        """Against the real tree: duplicates go and the order is the tree's, whatever was submitted."""
        mgr = _mock_manager()
        mgr.rights = flat_rights_tree(ALL_RIGHTS)
        first, second = mgr.rights[1].name, mgr.rights[2].name

        group = GroupsManager.hydrate_group(mgr, {**SAMPLE_GROUP_DICT, 'rights': [second, first, second]})

        assert [right.name for right in group.rights] == [first, second]

    def test_the_model_serialises_to_the_stored_and_the_read_form(self) -> None:
        """One model: name strings for the write, full right dicts with the same names for the answer."""
        mgr = _mock_manager()
        mgr.rights = flat_rights_tree(ALL_RIGHTS)
        names: list[str] = [mgr.rights[1].name, mgr.rights[2].name]

        group = GroupsManager.hydrate_group(mgr, {**SAMPLE_GROUP_DICT, 'rights': names})

        assert CmdbUserGroup.to_json(group, True)['rights'] == names
        assert [right['name'] for right in CmdbUserGroup.to_json(group)['rights']] == names


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      group_exists                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupExists:
    """``group_exists`` asks the id-only lookup about one public_id."""

    def test_an_existing_id_is_reported(self) -> None:
        """The id the lookup returns exists; only that one id was asked about."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = {REGULAR_GROUP_PUBLIC_ID}

        assert GroupsManager.group_exists(mgr, REGULAR_GROUP_PUBLIC_ID) is True
        mgr.find_existing_public_ids.assert_called_once_with([REGULAR_GROUP_PUBLIC_ID])

    def test_a_missing_id_is_not(self) -> None:
        """An empty answer means no such group."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = set()

        assert GroupsManager.group_exists(mgr, MISSING_GROUP_PUBLIC_ID) is False

    def test_the_document_is_never_built(self) -> None:
        """No model is built and no document read: the right tree is not touched."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = {REGULAR_GROUP_PUBLIC_ID}

        with patch.object(CmdbUserGroup, 'from_data') as from_data_mock:
            GroupsManager.group_exists(mgr, REGULAR_GROUP_PUBLIC_ID)

        from_data_mock.assert_not_called()
        mgr.get_item.assert_not_called()

    def test_a_failed_lookup_propagates(self) -> None:
        """The lookup's GroupsManagerGetError reaches the caller unchanged."""
        mgr = _mock_manager()
        failure = GroupsManagerGetError('boom')
        mgr.find_existing_public_ids.side_effect = failure

        with pytest.raises(GroupsManagerGetError) as exc_info:
            GroupsManager.group_exists(mgr, REGULAR_GROUP_PUBLIC_ID)

        assert exc_info.value is failure


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 canonical_right_names                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCanonicalRightNames:
    """``canonical_right_names`` is the create's form of the list an update stores."""

    def test_each_name_once_in_tree_order(self) -> None:
        """Duplicates go and the order is the tree's."""
        mgr = _mock_manager()
        mgr.rights = flat_rights_tree(ALL_RIGHTS)
        first, second = mgr.rights[1].name, mgr.rights[2].name

        assert GroupsManager.canonical_right_names(mgr, [second, first, second]) == [first, second]

    def test_equals_what_the_update_stores(self) -> None:
        """For the same input the create's list is the update's: the hydrated model in its stored form."""
        mgr = _mock_manager()
        mgr.rights = flat_rights_tree(ALL_RIGHTS)
        submitted: list[str] = [mgr.rights[5].name, MASTER_RIGHT_NAME, mgr.rights[5].name]

        hydrated = GroupsManager.hydrate_group(mgr, {**SAMPLE_GROUP_DICT, 'rights': submitted})

        assert GroupsManager.canonical_right_names(mgr, submitted) == CmdbUserGroup.to_json(hydrated, True)['rights']

    def test_an_empty_list_stays_empty(self) -> None:
        """No rights in, no rights out."""
        mgr = _mock_manager()
        mgr.rights = flat_rights_tree(ALL_RIGHTS)

        assert not GroupsManager.canonical_right_names(mgr, [])


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
