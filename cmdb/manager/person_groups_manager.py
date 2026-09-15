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
This module contains the implementation of the PersonGroupsManager

The manager owns the ``management.personGroup`` collection and is the mirror image of
``PersonsManager``: the same two-sided membership seen from the group's end, and the same ISMS cleanup
for a deleted reference target. Two things are worth knowing before changing anything:

**A group's deletion is a cascade, and the whole cascade lives here.** ``delete_with_follow_up`` clears
the ISMS references, removes the group from every CmdbPerson that lists it and only then deletes the
document. The person half used to be a second call made by the delete route, which meant any *other*
caller deleting a group left it listed on every member.

**A group is referenced where a person can be.** An IsmsRiskAssessment's owner, responsible persons and
auditor, and an IsmsControlMeasureAssignment's responsible party, each hold either kind - which is what
the '_ref_type' sibling of every one of those fields records, and why this cascade always filters on
both halves. Unlike a person, a group is never the risk *assessor* and never appears among the
interviewed persons
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.person_reference_helper import (
    add_member_to_documents,
    remove_member_from_documents,
    clear_polymorphic_risk_assessment_references,
    clear_control_measure_assignment_reference,
)

from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey, PersonReferenceType
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment

from cmdb.errors.manager.person_groups_manager import (
    PERSON_GROUPS_MANAGER_ERRORS,
    PersonGroupsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              PersonGroupsManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class PersonGroupsManager(GenericManager):
    """
    The PersonGroupsManager manages the interaction between CmdbPersonGroups and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, CmdbPersonGroup, PERSON_GROUPS_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes a CmdbPersonGroup and cleans all affected collections from it

        The complete cascade: the ISMS references are cleared, the group is removed from every
        CmdbPerson that lists it, and the document is deleted last, so an interrupted run leaves the
        group in place rather than leaving references to a group that no longer exists

        Args:
            public_id (int): public_id of CmdbPersonGroup which should be deleted

        Raises:
            PersonGroupsManagerDeleteError: If any step of the cascade or the deletion itself fails

        Returns:
            bool: True if deletion was a success, else False
        """
        try:
            self.remove_person_group_from_risk_assessments(public_id)
            self.remove_person_group_from_control_measure_assignments(public_id)
            self.remove_person_group_from_persons(public_id)

            return self.delete_item(public_id)
        except Exception as err:
            raise PersonGroupsManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def update_person_in_groups(self, person_id: int, groups_to_add: list[int], groups_to_delete: list[int]) -> None:
        """
        Updates a CmdbPerson in CmdbPersonGroups during an update operation

        Args:
            person_id (int): public_id of CmdbPerson which should be updated
            groups_to_add (list[int]): public_id's of CmdbPersonGroups where the CmdbPerson should be added
            groups_to_delete (list[int]): list of CmdbPersonGroup public_id's which should be deleted
        """
        self.add_person_to_groups(person_id, groups_to_add)
        self.delete_person_from_groups(person_id, groups_to_delete)


    def add_person_to_groups(self, person_id: int, group_ids: list[int]) -> None:
        """
        Adds a CmdbPerson to the 'group_members' of the given CmdbPersonGroups in a single bulk update

        Args:
            person_id (int): public_id of CmdbPerson which should be added
            group_ids (list[int]): public_id's of CmdbPersonGroups where the CmdbPerson should be added
        """
        add_member_to_documents(
            self.dbm,
            self.db_name,
            self.collection,
            PersonGroupKey.GROUP_MEMBERS.value,
            person_id,
            group_ids,
        )


    def delete_person_from_groups(self, person_id: int, groups_ids: list[int] = None) -> None:
        """
        Removes a CmdbPerson from the 'group_members' of CmdbPersonGroups in a single bulk '$pull' update

        When groups_ids is provided the pull is restricted to those CmdbPersonGroups, otherwise it is
        applied to every CmdbPersonGroup that lists the person as a member

        Args:
            person_id (int): public_id of CmdbPerson which should be removed
            groups_ids (list[int], optional): public_id's of the CmdbPersonGroups to update. Defaults to None
        """
        remove_member_from_documents(
            self.dbm,
            self.db_name,
            self.collection,
            PersonGroupKey.GROUP_MEMBERS.value,
            person_id,
            groups_ids,
        )


    def remove_person_group_from_persons(self, person_group_id: int) -> None:
        """
        Removes a deleted CmdbPersonGroup from the 'groups' of every CmdbPerson listing it

        The person side of the two-sided membership. Written straight to the person collection rather
        than through PersonsManager, because a manager must not depend on another manager

        Args:
            person_group_id (int): public_id of the deleted CmdbPersonGroup
        """
        remove_member_from_documents(
            self.dbm,
            self.db_name,
            CmdbPerson.COLLECTION,
            PersonKey.GROUPS.value,
            person_group_id,
        )


    def remove_person_group_from_risk_assessments(self, deleted_person_group_id: int) -> None:
        """
        Nulls every IsmsRiskAssessment reference naming the deleted CmdbPersonGroup

        The owner, the responsible persons and the auditor may each be a group; each is filtered by its
        '_ref_type' sibling, so a CmdbPerson with the same public_id keeps their references

        Args:
            deleted_person_group_id (int): The public_id of the deleted CmdbPersonGroup
        """
        clear_polymorphic_risk_assessment_references(
            self.dbm,
            self.db_name,
            IsmsRiskAssessment.COLLECTION,
            deleted_person_group_id,
            PersonReferenceType.PERSON_GROUP,
        )


    def remove_person_group_from_control_measure_assignments(self, deleted_person_group_id: int) -> None:
        """
        Nulls the 'responsible_for_implementation_id' of every IsmsControlMeasureAssignment that names
        the deleted CmdbPersonGroup

        Filtered by the field's '_ref_type' sibling, so an assignment whose responsible party is the
        CmdbPerson with the same public_id keeps it

        Args:
            deleted_person_group_id (int): The public_id of the deleted CmdbPersonGroup
        """
        clear_control_measure_assignment_reference(
            self.dbm,
            self.db_name,
            IsmsControlMeasureAssignment.COLLECTION,
            deleted_person_group_id,
            PersonReferenceType.PERSON_GROUP,
        )
