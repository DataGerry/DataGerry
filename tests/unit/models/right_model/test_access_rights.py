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
Unit tests of the access rule rights (``base.access.*``)

Pinned: the view right, the three edit rights and their wildcards are in the catalogue, in their own branch, named
and labelled by their families; each is granted by its own wildcard, by ``base.access.*`` and by the master right
``base.*`` - so the administrators hold them - but not by a sibling family's wildcard nor by the user management or
framework wildcards. Pure: no Mongo, no Flask
"""
import pytest

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.right_model.all_rights import ACCESS_RIGHTS, ALL_RIGHTS, ALL_RIGHTS_FLAT, flat_rights_tree
from cmdb.models.right_model.access_rights import AccessRight, AssignmentRight, FieldClassRight, ScopeRoleRight
from cmdb.models.right_model.base_right import BaseRight
# -------------------------------------------------------------------------------------------------------------------- #

VIEW: str = 'base.access.view'
FIELD_CLASS_EDIT: str = 'base.access.fieldclass.edit'
SCOPE_ROLE_EDIT: str = 'base.access.scoperole.edit'
ASSIGNMENT_EDIT: str = 'base.access.assignment.edit'
SPECIFIC: list[str] = [VIEW, FIELD_CLASS_EDIT, SCOPE_ROLE_EDIT, ASSIGNMENT_EDIT]
WILDCARDS: list[str] = ['base.access.*', 'base.access.fieldclass.*', 'base.access.scoperole.*',
                        'base.access.assignment.*']
GROUP_ID: int = 7
GROUP_NAME: str = 'access-right-group'


def _catalogue_right(name: str) -> BaseRight:
    """The catalogue's right of that name"""
    return next(right for right in ALL_RIGHTS_FLAT if right.name == name)


def _grants(held: str, asked: str) -> bool:
    """Whether a group holding just the right ``held`` holds ``asked``"""
    group = CmdbUserGroup(public_id=GROUP_ID, name=GROUP_NAME, rights=[_catalogue_right(held)])

    return group.has_right(asked) or group.has_extended_right(asked)


class TestTheCatalogue:
    """Where the rights sit and how they are named."""

    def test_the_branch_holds_exactly_these_rights(self) -> None:
        """Four rights and four wildcards"""
        assert sorted(right.name for right in flat_rights_tree(ACCESS_RIGHTS)) == sorted(SPECIFIC + WILDCARDS)

    def test_the_branch_is_part_of_the_catalogue(self) -> None:
        """The rights routes and the group screens offer it"""
        assert ACCESS_RIGHTS in ALL_RIGHTS
        assert set(SPECIFIC + WILDCARDS) <= {right.name for right in ALL_RIGHTS_FLAT}

    @pytest.mark.parametrize('name, family, label', [
        (VIEW, AccessRight, 'access.view'),
        (FIELD_CLASS_EDIT, FieldClassRight, 'fieldclass.edit'),
        (SCOPE_ROLE_EDIT, ScopeRoleRight, 'scoperole.edit'),
        (ASSIGNMENT_EDIT, AssignmentRight, 'assignment.edit'),
    ])
    def test_the_family_names_and_labels_each_right(self, name: str, family: type, label: str) -> None:
        """Built name-first from its family; every right describes what it unlocks"""
        right: BaseRight = _catalogue_right(name)

        assert isinstance(right, family) and issubclass(family, AccessRight)
        assert (right.label, bool(right.description)) == (label, True)


class TestWhoHoldsThem:
    """The wildcards above a right grant it; the siblings and the other areas do not."""

    @pytest.mark.parametrize('asked', SPECIFIC)
    @pytest.mark.parametrize('held', ['base.*', 'base.access.*'])
    def test_the_master_and_the_area_wildcard_grant_every_right(self, held: str, asked: str) -> None:
        """The administrators hold them through base.*"""
        assert _grants(held, asked)

    @pytest.mark.parametrize('held, asked', [
        ('base.access.fieldclass.*', FIELD_CLASS_EDIT),
        ('base.access.scoperole.*', SCOPE_ROLE_EDIT),
        ('base.access.assignment.*', ASSIGNMENT_EDIT),
    ])
    def test_a_family_wildcard_grants_its_edit_right(self, held: str, asked: str) -> None:
        """fieldclass.* grants fieldclass.edit"""
        assert _grants(held, asked)

    @pytest.mark.parametrize('held, asked', [
        ('base.access.fieldclass.*', SCOPE_ROLE_EDIT),
        ('base.access.scoperole.*', ASSIGNMENT_EDIT),
        ('base.access.assignment.*', VIEW),
        (VIEW, FIELD_CLASS_EDIT),
        ('base.user-management.*', ASSIGNMENT_EDIT),
        ('base.framework.*', SCOPE_ROLE_EDIT),
    ], ids=['class-not-role', 'role-not-assignment', 'assignment-not-view', 'view-not-edit', 'user-management',
            'framework'])
    def test_no_other_right_grants_it(self, held: str, asked: str) -> None:
        """Siblings, the view right and the other areas grant nothing here"""
        assert not _grants(held, asked)
