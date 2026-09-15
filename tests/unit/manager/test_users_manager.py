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
Unit tests for cmdb.manager.users_manager.UsersManager

Pure tests: no Mongo. Each method is driven against a ``MagicMock(spec=UsersManager)`` with its
database primitives (find / get_one / get_one_by / insert / update / update_many / delete /
delete_many / delete_many_from_other_collection) stubbed, so only the manager's own behaviour is
exercised - the projections it reads with, the queries it builds, the admin refusals, the settings
cascade and the mapping of every BaseManager failure onto this manager's error family.

The group-delete redistribution gets the most attention here, because a mistake in it is silent: a
user left pointing at a deleted group still authenticates but is refused every right (see
``route_utils.user_has_right``, which resolves their group to None). The same paths are pinned
against real MongoDB in tests/integration/management/test_integration_users_manager_extra.py.
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.manager.users_manager_constants import MINIMAL_USER_PROJECTION, USER_ID_PROJECTION
from cmdb.models.group_model import GroupDeleteMode
from cmdb.models.settings_model import CmdbUserSetting, UserSettingKey
from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.users_manager import (
    UsersManagerActionError,
    UsersManagerDeleteError,
    UsersManagerGetError,
    UsersManagerInitError,
    UsersManagerInsertError,
    UsersManagerIterationError,
    UsersManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 42
OTHER_USER_ID: int = 43
SRC_GROUP_ID: int = 9910
DST_GROUP_ID: int = 9911

SAMPLE_USER_DICT: dict[str, Any] = {
    'public_id': USER_ID,
    'user_name': 'tester',
    'active': True,
    'group_id': SRC_GROUP_ID,
}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a UsersManager instance."""
    return MagicMock(spec=UsersManager)


def _user(public_id: int = USER_ID) -> CmdbUser:
    """A CmdbUser carrying only what these tests read off it."""
    return CmdbUser(public_id=public_id, user_name=f'user-{public_id}', active=True, group_id=SRC_GROUP_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       __init__                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """Wiring the manager onto its collection."""

    def test_binds_the_user_collection(self) -> None:
        """Every read and write below targets whatever collection is set here."""
        manager = UsersManager(MagicMock())

        assert manager.collection == CmdbUser.COLLECTION

    def test_a_failed_wiring_becomes_an_init_error(self) -> None:
        """The route builds managers through ManagerProvider, which expects a typed failure."""
        with patch.object(BaseManager, '__init__', side_effect=RuntimeError('no connection')):
            with pytest.raises(UsersManagerInitError):
                UsersManager(MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_minimal_users_by_ids                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetMinimalUsersByIds:
    """The display-only read: one query, a fixed projection, and no query at all for no ids."""

    def test_no_ids_skips_the_query(self) -> None:
        """An empty id list must not become {'$in': []}, which would be a pointless round-trip."""
        mgr = _mock_manager()

        assert UsersManager.get_minimal_users_by_ids(mgr, []) == []
        mgr.find.assert_not_called()

    def test_reads_with_the_minimal_projection(self) -> None:
        """The password digest and the rest of the account record must not leave the database."""
        mgr = _mock_manager()
        mgr.find.return_value = [{'public_id': USER_ID}]

        result = UsersManager.get_minimal_users_by_ids(mgr, [USER_ID, OTHER_USER_ID])

        mgr.find.assert_called_once_with(
            criteria={'public_id': {'$in': [USER_ID, OTHER_USER_ID]}},
            projection=MINIMAL_USER_PROJECTION,
        )
        assert result == [{'public_id': USER_ID}]

    def test_wraps_a_read_failure(self) -> None:
        """A BaseManagerGetError must not reach the route, which has no arm for it (500)."""
        mgr = _mock_manager()
        mgr.find.side_effect = BaseManagerGetError('boom')

        with pytest.raises(UsersManagerGetError):
            UsersManager.get_minimal_users_by_ids(mgr, [USER_ID])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     insert_user                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertUser:
    """A CmdbUser is serialised first; a dict is stored as given."""

    def test_serialises_a_cmdb_user(self) -> None:
        """The model instance is converted, never handed to pymongo as an object."""
        mgr = _mock_manager()
        mgr.insert.return_value = USER_ID

        result = UsersManager.insert_user(mgr, _user())

        assert result == USER_ID
        assert isinstance(mgr.insert.call_args.args[0], dict)

    def test_stores_a_dict_unchanged(self) -> None:
        """A dict payload reaches insert as-is."""
        mgr = _mock_manager()
        mgr.insert.return_value = USER_ID

        UsersManager.insert_user(mgr, dict(SAMPLE_USER_DICT))

        mgr.insert.assert_called_once_with(SAMPLE_USER_DICT)

    def test_wraps_an_insert_failure(self) -> None:
        """A duplicate user_name (unique index) has to surface as this manager's insert error."""
        mgr = _mock_manager()
        mgr.insert.side_effect = RuntimeError('duplicate key')

        with pytest.raises(UsersManagerInsertError):
            UsersManager.insert_user(mgr, dict(SAMPLE_USER_DICT))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  get_user / get_user_by                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetUser:
    """Reading one user by public_id."""

    def test_deserialises_the_document(self) -> None:
        """The route layer expects a CmdbUser, not the raw document."""
        mgr = _mock_manager()
        mgr.get_one.return_value = dict(SAMPLE_USER_DICT)

        result = UsersManager.get_user(mgr, USER_ID)

        assert isinstance(result, CmdbUser)
        assert result.public_id == USER_ID

    def test_a_missing_user_is_none_not_an_error(self) -> None:
        """user_has_right and the delete route both branch on None; an error would be a 500."""
        mgr = _mock_manager()
        mgr.get_one.return_value = None

        assert UsersManager.get_user(mgr, USER_ID) is None

    def test_wraps_a_read_failure(self) -> None:
        """A failure is not a missing user - the two must stay distinguishable."""
        mgr = _mock_manager()
        mgr.get_one.side_effect = BaseManagerGetError('boom')

        with pytest.raises(UsersManagerGetError):
            UsersManager.get_user(mgr, USER_ID)


class TestGetUserBy:
    """Reading one user by an arbitrary query - the login path's lookup."""

    def test_delegates_to_get_one_by(self) -> None:
        """Find-one-or-None belongs to BaseManager; this method must not re-implement it."""
        mgr = _mock_manager()
        mgr.get_one_by.return_value = dict(SAMPLE_USER_DICT)

        result = UsersManager.get_user_by(mgr, {'user_name': 'tester'})

        mgr.get_one_by.assert_called_once_with({'user_name': 'tester'})
        assert isinstance(result, CmdbUser)

    def test_a_missing_user_is_none(self) -> None:
        """No match is None - not an exception, and not a fabricated user."""
        mgr = _mock_manager()
        mgr.get_one_by.return_value = None

        assert UsersManager.get_user_by(mgr, {'user_name': 'nobody'}) is None

    def test_wraps_a_read_failure(self) -> None:
        """An outage must not be reported to the caller as 'no such user'."""
        mgr = _mock_manager()
        mgr.get_one_by.side_effect = BaseManagerGetError('boom')

        with pytest.raises(UsersManagerGetError):
            UsersManager.get_user_by(mgr, {'user_name': 'tester'})


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_many_users / get_user_lookup                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetManyUsers:
    """Reading a user set by query."""

    def test_no_query_means_all_users(self) -> None:
        """None must become {}, not be passed through as a filter."""
        mgr = _mock_manager()
        mgr.get.return_value = []

        UsersManager.get_many_users(mgr, None)

        mgr.get.assert_called_once_with(filter={})

    def test_deserialises_every_document(self) -> None:
        """The caller iterates CmdbUsers, so every row has to be converted."""
        mgr = _mock_manager()
        mgr.get.return_value = [dict(SAMPLE_USER_DICT), {**SAMPLE_USER_DICT, 'public_id': OTHER_USER_ID}]

        result = UsersManager.get_many_users(mgr, {'group_id': SRC_GROUP_ID})

        assert [user.public_id for user in result] == [USER_ID, OTHER_USER_ID]

    def test_wraps_a_read_failure(self) -> None:
        """Covers both a failed query and a document that will not deserialise."""
        mgr = _mock_manager()
        mgr.get.side_effect = BaseManagerGetError('boom')

        with pytest.raises(UsersManagerGetError):
            UsersManager.get_many_users(mgr, {})


class TestGetUserLookup:
    """The bulk author/editor lookup behind the type overview and the object render."""

    def test_keys_the_result_by_public_id(self) -> None:
        """Consumers index this by author_id, so the key must be the user's public_id."""
        mgr = _mock_manager()
        mgr.find.return_value = [dict(SAMPLE_USER_DICT), {**SAMPLE_USER_DICT, 'public_id': OTHER_USER_ID}]

        result = UsersManager.get_user_lookup(mgr, [USER_ID, OTHER_USER_ID])

        assert sorted(result) == [USER_ID, OTHER_USER_ID]
        assert all(isinstance(user, CmdbUser) for user in result.values())

    def test_reads_every_id_in_one_query(self) -> None:
        """One $in, not one query per author - this runs for every row of a listing."""
        mgr = _mock_manager()
        mgr.find.return_value = []

        UsersManager.get_user_lookup(mgr, [USER_ID, OTHER_USER_ID])

        mgr.find.assert_called_once_with(criteria={'public_id': {'$in': [USER_ID, OTHER_USER_ID]}})

    def test_wraps_a_read_failure(self) -> None:
        """Its callers' error maps know UsersManagerGetError; a BaseManager error becomes a 500."""
        mgr = _mock_manager()
        mgr.find.side_effect = BaseManagerGetError('boom')

        with pytest.raises(UsersManagerGetError):
            UsersManager.get_user_lookup(mgr, [USER_ID])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       iterate                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterate:
    """The paged read behind GET /users."""

    def test_returns_the_total_alongside_the_page(self) -> None:
        """The pager needs the match count, not the page length."""
        mgr = _mock_manager()
        mgr.iterate_query.return_value = ([dict(SAMPLE_USER_DICT)], 17)

        result = UsersManager.iterate(mgr, MagicMock())

        assert result.total == 17
        assert len(result.results) == 1

    def test_wraps_an_iteration_failure(self) -> None:
        """A bad filter has to surface as this manager's iteration error."""
        mgr = _mock_manager()
        mgr.iterate_query.side_effect = RuntimeError('bad pipeline')

        with pytest.raises(UsersManagerIterationError):
            UsersManager.iterate(mgr, MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     update_user                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateUser:
    """Writing one user."""

    def test_matches_on_public_id(self) -> None:
        """Matching on anything else could rewrite the wrong account."""
        mgr = _mock_manager()

        UsersManager.update_user(mgr, USER_ID, dict(SAMPLE_USER_DICT))

        mgr.update.assert_called_once_with(criteria={'public_id': USER_ID}, data=SAMPLE_USER_DICT)

    def test_serialises_a_cmdb_user(self) -> None:
        """A model instance is converted before it reaches the driver."""
        mgr = _mock_manager()

        UsersManager.update_user(mgr, USER_ID, _user())

        assert isinstance(mgr.update.call_args.kwargs['data'], dict)

    def test_wraps_an_update_failure(self) -> None:
        """The route maps this to its own 400."""
        mgr = _mock_manager()
        mgr.update.side_effect = BaseManagerUpdateError('boom')

        with pytest.raises(UsersManagerUpdateError):
            UsersManager.update_user(mgr, USER_ID, dict(SAMPLE_USER_DICT))


# -------------------------------------------------------------------------------------------------------------------- #
#                                            delete_user / _delete_user_settings                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteUser:
    """Deleting one user, and taking its settings with it."""

    def test_refuses_the_admin_user(self) -> None:
        """The bootstrap admin is the only account that can always administer the system."""
        mgr = _mock_manager()

        with pytest.raises(UsersManagerDeleteError):
            UsersManager.delete_user(mgr, CmdbUser.ADMIN_PUBLIC_ID)

        mgr.delete.assert_not_called()
        mgr.delete_many_from_other_collection.assert_not_called()

    def test_deletes_by_public_id_and_reports_the_outcome(self) -> None:
        """The route answers 200 on the strength of this boolean."""
        mgr = _mock_manager()
        mgr.delete.return_value = True

        assert UsersManager.delete_user(mgr, USER_ID) is True
        mgr.delete.assert_called_once_with({'public_id': USER_ID})

    def test_cascades_into_the_settings_collection(self) -> None:
        """Nothing else prunes user settings, so a skipped cascade orphans them forever."""
        mgr = _mock_manager()
        mgr.delete.return_value = True

        UsersManager.delete_user(mgr, USER_ID)

        mgr._delete_user_settings.assert_called_once_with([USER_ID])

    def test_wraps_a_delete_failure(self) -> None:
        """A driver failure becomes this manager's delete error."""
        mgr = _mock_manager()
        mgr.delete.side_effect = BaseManagerDeleteError('boom')

        with pytest.raises(UsersManagerDeleteError):
            UsersManager.delete_user(mgr, USER_ID)

    def test_a_failing_cascade_is_reported(self) -> None:
        """Silently swallowing it would report a clean delete that left rows behind."""
        mgr = _mock_manager()
        mgr.delete.return_value = True
        mgr._delete_user_settings.side_effect = BaseManagerDeleteError('boom')

        with pytest.raises(UsersManagerDeleteError):
            UsersManager.delete_user(mgr, USER_ID)


class TestDeleteUserSettings:
    """The cross-collection cascade itself."""

    def test_no_ids_skips_the_query(self) -> None:
        """An empty $in would delete nothing but still cost a round-trip."""
        mgr = _mock_manager()

        UsersManager._delete_user_settings(mgr, [])

        mgr.delete_many_from_other_collection.assert_not_called()

    def test_targets_the_settings_collection_by_user_id(self) -> None:
        """Settings reference their user by public_id only - there is no back-reference to follow."""
        mgr = _mock_manager()

        UsersManager._delete_user_settings(mgr, [USER_ID, OTHER_USER_ID])

        mgr.delete_many_from_other_collection.assert_called_once_with(
            CmdbUserSetting.COLLECTION,
            {UserSettingKey.USER_ID.value: {'$in': [USER_ID, OTHER_USER_ID]}},
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                            handle_users_on_group_delete                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleUsersOnGroupDeleteDispatch:
    """Which branch runs - and what happens when the answer is 'neither'."""

    def test_move_runs_the_move_branch(self) -> None:
        """MOVE must not delete anybody."""
        mgr = _mock_manager()

        UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, GroupDeleteMode.MOVE, DST_GROUP_ID)

        mgr._move_group_members.assert_called_once_with(SRC_GROUP_ID, DST_GROUP_ID)
        mgr._delete_group_members.assert_not_called()

    def test_delete_runs_the_delete_branch(self) -> None:
        """DELETE must not move anybody."""
        mgr = _mock_manager()

        UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, GroupDeleteMode.DELETE, None)

        mgr._delete_group_members.assert_called_once_with(SRC_GROUP_ID)
        mgr._move_group_members.assert_not_called()

    @pytest.mark.parametrize('action', ['BOGUS', 'null', '', 'move', None])
    def test_an_unsupported_action_refuses_instead_of_no_op(self, action: Any) -> None:
        """Falling through silently would delete the group and strand every member without rights."""
        mgr = _mock_manager()

        with pytest.raises(UsersManagerActionError):
            UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, action, DST_GROUP_ID)

        mgr._move_group_members.assert_not_called()
        mgr._delete_group_members.assert_not_called()

    def test_the_string_form_of_the_enum_still_dispatches(self) -> None:
        """Flask hands query values over as strings; GroupDeleteMode is a str enum for that reason."""
        mgr = _mock_manager()

        UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, 'MOVE', DST_GROUP_ID)

        mgr._move_group_members.assert_called_once_with(SRC_GROUP_ID, DST_GROUP_ID)


class TestHandleUsersOnGroupDeleteErrorMapping:
    """Every BaseManager failure has to arrive at the route as a UsersManager error."""

    def test_a_base_update_error_becomes_an_update_error(self) -> None:
        """The route maps this to 'Failed to move User to Group' - a 400, not a 500."""
        mgr = _mock_manager()
        mgr._move_group_members.side_effect = BaseManagerUpdateError('boom')

        with pytest.raises(UsersManagerUpdateError):
            UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, GroupDeleteMode.MOVE, DST_GROUP_ID)

    def test_a_base_delete_error_becomes_a_delete_error(self) -> None:
        """Same for a failed member delete."""
        mgr = _mock_manager()
        mgr._delete_group_members.side_effect = BaseManagerDeleteError('boom')

        with pytest.raises(UsersManagerDeleteError):
            UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, GroupDeleteMode.DELETE, None)

    def test_a_base_get_error_becomes_a_get_error(self) -> None:
        """And for the member read that the delete branch does first."""
        mgr = _mock_manager()
        mgr._delete_group_members.side_effect = BaseManagerGetError('boom')

        with pytest.raises(UsersManagerGetError):
            UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, GroupDeleteMode.DELETE, None)

    @pytest.mark.parametrize(
        'raised',
        [UsersManagerDeleteError('admin'), UsersManagerUpdateError('no target'), UsersManagerGetError('read')],
        ids=['delete', 'update', 'get'],
    )
    def test_this_managers_own_errors_pass_through_unchanged(self, raised: Exception) -> None:
        """Re-wrapping would lose which rule fired, and the route answers a different message per rule."""
        mgr = _mock_manager()
        mgr._delete_group_members.side_effect = raised

        with pytest.raises(type(raised)) as excinfo:
            UsersManager.handle_users_on_group_delete(mgr, SRC_GROUP_ID, GroupDeleteMode.DELETE, None)

        assert excinfo.value is raised


class TestMoveGroupMembers:
    """MOVE: one predicate, one constant value, one statement."""

    def test_moves_every_member_in_a_single_update(self) -> None:
        """Reading the members to build one UpdateOne each would be N reads and N writes for one value."""
        mgr = _mock_manager()

        UsersManager._move_group_members(mgr, SRC_GROUP_ID, DST_GROUP_ID)

        mgr.update_many.assert_called_once_with({'group_id': SRC_GROUP_ID}, {'group_id': DST_GROUP_ID})
        mgr.find.assert_not_called()
        mgr.get_many_users.assert_not_called()

    def test_coerces_a_numeric_string_target(self) -> None:
        """The target arrives from a query string, and group_id is stored as an int."""
        mgr = _mock_manager()

        UsersManager._move_group_members(mgr, SRC_GROUP_ID, '9911')

        assert mgr.update_many.call_args.args[1] == {'group_id': DST_GROUP_ID}

    @pytest.mark.parametrize('target', [None, 0], ids=['missing', 'zero'])
    def test_refuses_without_a_target(self, target: Any) -> None:
        """Moving to nowhere would strand the members exactly as a silent no-op would."""
        mgr = _mock_manager()

        with pytest.raises(UsersManagerUpdateError):
            UsersManager._move_group_members(mgr, SRC_GROUP_ID, target)

        mgr.update_many.assert_not_called()


class TestDeleteGroupMembers:
    """DELETE: refuse for the admin, then delete the members and their settings."""

    def test_refuses_when_the_admin_is_a_member(self) -> None:
        """The check runs before anything is deleted, so the group survives intact."""
        mgr = _mock_manager()
        mgr.get_one_by.return_value = {'public_id': CmdbUser.ADMIN_PUBLIC_ID}

        with pytest.raises(UsersManagerDeleteError):
            UsersManager._delete_group_members(mgr, SRC_GROUP_ID)

        mgr.delete_many.assert_not_called()
        mgr._delete_user_settings.assert_not_called()

    def test_looks_for_the_admin_in_this_group_only(self) -> None:
        """A query on public_id alone would refuse every group delete."""
        mgr = _mock_manager()
        mgr.get_one_by.return_value = None
        mgr.find.return_value = []

        UsersManager._delete_group_members(mgr, SRC_GROUP_ID)

        mgr.get_one_by.assert_called_once_with({
            'group_id': SRC_GROUP_ID,
            'public_id': CmdbUser.ADMIN_PUBLIC_ID,
        })

    def test_an_empty_group_is_a_no_op(self) -> None:
        """No members means nothing to delete and nothing to cascade."""
        mgr = _mock_manager()
        mgr.get_one_by.return_value = None
        mgr.find.return_value = []

        UsersManager._delete_group_members(mgr, SRC_GROUP_ID)

        mgr.delete_many.assert_not_called()
        mgr._delete_user_settings.assert_not_called()

    def test_reads_only_the_member_ids(self) -> None:
        """The cascade needs the ids; loading whole user documents for them would be waste."""
        mgr = _mock_manager()
        mgr.get_one_by.return_value = None
        mgr.find.return_value = [{'public_id': USER_ID}]

        UsersManager._delete_group_members(mgr, SRC_GROUP_ID)

        mgr.find.assert_called_once_with(criteria={'group_id': SRC_GROUP_ID}, projection=USER_ID_PROJECTION)

    def test_deletes_the_members_and_cascades_their_settings(self) -> None:
        """Both halves, with the ids read before the users are gone."""
        mgr = _mock_manager()
        mgr.get_one_by.return_value = None
        mgr.find.return_value = [{'public_id': USER_ID}, {'public_id': OTHER_USER_ID}]

        UsersManager._delete_group_members(mgr, SRC_GROUP_ID)

        mgr.delete_many.assert_called_once_with({'group_id': SRC_GROUP_ID})
        mgr._delete_user_settings.assert_called_once_with([USER_ID, OTHER_USER_ID])
