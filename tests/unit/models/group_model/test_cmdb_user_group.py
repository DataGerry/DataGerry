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
Unit tests for cmdb.models.group_model.cmdb_user_group

Pure: no Mongo, no Flask. A CmdbUserGroup is where authorisation actually gets decided -
`route_utils.user_has_right` asks `has_right` and then `has_extended_right` for the right named on
the route - so the two membership checks and the two serialisers are what this pins.

Three regressions are pinned by name:

* `has_extended_right` used to recurse forever on a name carrying no dot (`rsplit` returns such a
  name unchanged), which meant a RecursionError instead of a denial
* `to_json` built its rights list outside its own try block, so a failure there escaped raw instead
  of as CmdbUserGroupToJsonError
* the two serialisation modes are asymmetric on purpose: `insert_mode=True` writes right NAMES (the
  stored form) and False writes full dicts (the API form), and `from_data` resolves names back into
  instances - so the round trip is what guards against drift between them
"""
from typing import Any

import pytest

from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels

from cmdb.errors.models.cmdb_user_group import (
    CmdbUserGroupInitError,
    CmdbUserGroupInitFromDataError,
    CmdbUserGroupToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 42
GROUP_NAME: str = 'operators'
EXPECTED_DEFAULT_LABEL: str = 'Operators'
CUSTOM_LABEL: str = 'Ops team'

MASTER_RIGHT: str = 'base.*'
OBJECT_BRANCH_RIGHT: str = 'base.framework.object.*'
OBJECT_VIEW_RIGHT: str = 'base.framework.object.view'
TYPE_VIEW_RIGHT: str = 'base.framework.type.view'
UNKNOWN_RIGHT: str = 'base.does.not.exist'

# Names carrying no dot at all - the shape that used to recurse forever
UNQUALIFIED_RIGHT: str = 'nodots'
EMPTY_RIGHT: str = ''


def _right(qualified_name: str) -> BaseRight:
    """Builds a BaseRight whose stored name is exactly `qualified_name`."""
    prefix, _, leaf = qualified_name.rpartition('.')

    class _Right(BaseRight):
        """A right with the PREFIX needed to produce the requested qualified name."""
        PREFIX = prefix

    return _Right(Levels.NOTSET, leaf)


def _group(**overrides: Any) -> CmdbUserGroup:
    """Builds a CmdbUserGroup with the mandatory arguments filled in."""
    kwargs: dict[str, Any] = {'public_id': PUBLIC_ID, 'name': GROUP_NAME}
    kwargs.update(overrides)

    return CmdbUserGroup(**kwargs)


class TestInit:
    """Tests for the CmdbUserGroup constructor"""

    def test_label_defaults_to_the_titled_name(self) -> None:
        """Without a label the group is labelled from its name."""
        assert _group().label == EXPECTED_DEFAULT_LABEL

    def test_explicit_label_wins(self) -> None:
        """A label passed in is kept verbatim."""
        assert _group(label=CUSTOM_LABEL).label == CUSTOM_LABEL

    def test_rights_default_to_empty(self) -> None:
        """A group without rights holds an empty list, never None."""
        assert _group().rights == []

    def test_missing_name_raises_init_error(self) -> None:
        """A None name fails on the label fallback and surfaces as CmdbUserGroupInitError."""
        with pytest.raises(CmdbUserGroupInitError):
            CmdbUserGroup(public_id=PUBLIC_ID, name=None)


class TestFromData:
    """Tests for CmdbUserGroup.from_data, which resolves stored right names into instances"""

    def test_resolves_known_right_names(self) -> None:
        """Only the rights the document names are attached."""
        known: list[BaseRight] = [_right(MASTER_RIGHT), _right(OBJECT_VIEW_RIGHT)]
        group = CmdbUserGroup.from_data(
            {'public_id': PUBLIC_ID, 'name': GROUP_NAME, 'rights': [OBJECT_VIEW_RIGHT]},
            rights=known,
        )

        assert [right.name for right in group.rights] == [OBJECT_VIEW_RIGHT]

    def test_drops_names_not_in_the_known_rights(self) -> None:
        """A stored name the tree no longer declares is dropped rather than raising."""
        group = CmdbUserGroup.from_data(
            {'public_id': PUBLIC_ID, 'name': GROUP_NAME, 'rights': [UNKNOWN_RIGHT]},
            rights=[_right(OBJECT_VIEW_RIGHT)],
        )

        assert group.rights == []

    def test_without_known_rights_yields_no_rights(self) -> None:
        """Called without the rights catalogue, nothing can be resolved."""
        group = CmdbUserGroup.from_data(
            {'public_id': PUBLIC_ID, 'name': GROUP_NAME, 'rights': [OBJECT_VIEW_RIGHT]},
        )

        assert group.rights == []

    def test_tolerates_a_null_rights_key(self) -> None:
        """A document storing rights as null is read as 'no rights', not as a crash."""
        group = CmdbUserGroup.from_data(
            {'public_id': PUBLIC_ID, 'name': GROUP_NAME, 'rights': None},
            rights=[_right(OBJECT_VIEW_RIGHT)],
        )

        assert group.rights == []

    def test_tolerates_an_absent_rights_key(self) -> None:
        """A document with no rights key at all behaves the same way."""
        group = CmdbUserGroup.from_data(
            {'public_id': PUBLIC_ID, 'name': GROUP_NAME},
            rights=[_right(OBJECT_VIEW_RIGHT)],
        )

        assert group.rights == []

    def test_unusable_data_raises_from_data_error(self) -> None:
        """A document without a name fails as CmdbUserGroupInitFromDataError."""
        with pytest.raises(CmdbUserGroupInitFromDataError):
            CmdbUserGroup.from_data({'public_id': PUBLIC_ID})


class TestToJson:
    """Tests for CmdbUserGroup.to_json and its two asymmetric modes"""

    def test_insert_mode_serialises_right_names(self) -> None:
        """The stored form carries the qualified names only."""
        group = _group(rights=[_right(OBJECT_VIEW_RIGHT)])

        assert CmdbUserGroup.to_json(group, insert_mode=True)['rights'] == [OBJECT_VIEW_RIGHT]

    def test_api_mode_serialises_full_right_dicts(self) -> None:
        """The API form carries the full BaseRight dicts."""
        group = _group(rights=[_right(OBJECT_VIEW_RIGHT)])
        rights: list[Any] = CmdbUserGroup.to_json(group)['rights']

        assert len(rights) == 1
        assert rights[0]['name'] == OBJECT_VIEW_RIGHT
        assert set(rights[0]) == {'level', 'name', 'label', 'description', 'is_master'}

    def test_carries_identity_fields(self) -> None:
        """Both modes carry public_id, name and label."""
        result: dict[str, Any] = CmdbUserGroup.to_json(_group(label=CUSTOM_LABEL))

        assert result['public_id'] == PUBLIC_ID
        assert result['name'] == GROUP_NAME
        assert result['label'] == CUSTOM_LABEL

    def test_round_trips_through_the_stored_form(self) -> None:
        """insert_mode output feeds back through from_data unchanged - the drift guard."""
        known: list[BaseRight] = [_right(MASTER_RIGHT), _right(OBJECT_VIEW_RIGHT)]
        stored: dict[str, Any] = CmdbUserGroup.to_json(
            _group(rights=[_right(OBJECT_VIEW_RIGHT)]), insert_mode=True,
        )

        restored = CmdbUserGroup.from_data(stored, rights=known)

        assert [right.name for right in restored.rights] == [OBJECT_VIEW_RIGHT]
        assert restored.name == GROUP_NAME

    def test_failure_in_the_rights_list_is_wrapped(self) -> None:
        """A right that cannot be serialised surfaces as CmdbUserGroupToJsonError, not raw."""
        group = _group(rights=[object()])

        with pytest.raises(CmdbUserGroupToJsonError):
            CmdbUserGroup.to_json(group, insert_mode=True)


class TestHasRight:
    """Tests for the exact-match right check"""

    def test_finds_a_held_right(self) -> None:
        """An exactly matching qualified name is found."""
        assert _group(rights=[_right(OBJECT_VIEW_RIGHT)]).has_right(OBJECT_VIEW_RIGHT) is True

    def test_does_not_match_a_parent_right(self) -> None:
        """has_right is exact - a branch right does not satisfy it."""
        assert _group(rights=[_right(OBJECT_BRANCH_RIGHT)]).has_right(OBJECT_VIEW_RIGHT) is False

    def test_empty_group_holds_nothing(self) -> None:
        """A group without rights answers False."""
        assert _group().has_right(OBJECT_VIEW_RIGHT) is False


class TestHasExtendedRight:
    """Tests for the recursive branch-right walk"""

    def test_master_right_grants_everything(self) -> None:
        """'base.*' satisfies any right in the tree."""
        group = _group(rights=[_right(MASTER_RIGHT)])

        assert group.has_extended_right(OBJECT_VIEW_RIGHT) is True
        assert group.has_extended_right(TYPE_VIEW_RIGHT) is True

    def test_branch_right_grants_only_its_own_branch(self) -> None:
        """A branch wildcard grants below itself and nothing else."""
        group = _group(rights=[_right(OBJECT_BRANCH_RIGHT)])

        assert group.has_extended_right(OBJECT_VIEW_RIGHT) is True
        assert group.has_extended_right(TYPE_VIEW_RIGHT) is False

    def test_exact_right_alone_does_not_extend(self) -> None:
        """Holding the leaf itself is has_right's business, not this walk's."""
        assert _group(rights=[_right(OBJECT_VIEW_RIGHT)]).has_extended_right(OBJECT_VIEW_RIGHT) is False

    def test_empty_group_grants_nothing(self) -> None:
        """A group without rights denies every extended right."""
        assert _group().has_extended_right(OBJECT_VIEW_RIGHT) is False

    def test_unqualified_name_is_denied_without_recursing(self) -> None:
        """A name with no dot terminates as a denial - it used to recurse until RecursionError."""
        group = _group(rights=[])

        assert group.has_extended_right(UNQUALIFIED_RIGHT) is False
        assert group.has_extended_right(EMPTY_RIGHT) is False

    def test_root_name_is_denied_without_recursing(self) -> None:
        """'base' has nothing above it, so the walk stops there too."""
        assert _group(rights=[]).has_extended_right('base') is False
