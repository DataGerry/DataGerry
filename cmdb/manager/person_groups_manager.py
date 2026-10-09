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
document. The person half is not left to the delete route, so any *other* caller deleting a group
removes it from every member too. A create or update writes the persons' side through
``person_membership_helper.sync_membership`` in the route layer, where the write is recorded in the request's
WriteLedger - this manager writes the other side only as part of that cascade.

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
    remove_member_from_documents,
    clear_polymorphic_risk_assessment_references,
    clear_control_measure_assignment_reference,
)

from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.models.person_group_model import CmdbPersonGroup, PersonReferenceType
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
        CmdbPerson that lists it, and the document is deleted last, so an interrupted run never leaves
        references to a group that no longer exists. The writes are not undone here: the DELETE route
        records the inverse of each one beforehand (``record_delete_cascade``) and undoes them when this
        raises

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
