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
This module contains the implementation of the PersonsManager

The manager owns the ``management.person`` collection. Two things about it are worth knowing before
changing anything:

**A person's deletion is a cascade, and the whole cascade lives here.** ``delete_with_follow_up`` clears
the ISMS references, removes the person from every CmdbPersonGroup that lists them and only then
deletes the document. The group half used to be a second call made by the delete route, which meant any
*other* caller deleting a person left them listed in every group; the route now makes one call and this
manager is the single place that knows what deleting a person entails.

**Membership is two-sided and neither side is derived.** A person lists their groups and each group
lists its members, so a change has to be written to both. The methods here maintain the person side;
their mirror images in ``PersonGroupsManager`` maintain the group side, and both are thin wrappers over
``person_reference_helper``
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
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey

from cmdb.errors.manager.persons_manager import PERSONS_MANAGER_ERRORS, PersonsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                PersonsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class PersonsManager(GenericManager):
    """
    The PersonsManager manages the interaction between CmdbPersons and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, CmdbPerson, PERSONS_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes a CmdbPerson and cleans all affected collections from it

        The complete cascade: the ISMS references are cleared, the person is removed from every
        CmdbPersonGroup that lists them, and the document is deleted last, so an interrupted run leaves
        the person in place rather than leaving references to a person that no longer exists

        Args:
            public_id (int): public_id of CmdbPerson which should be deleted

        Raises:
            PersonsManagerDeleteError: If any step of the cascade or the deletion itself fails

        Returns:
            bool: True if deletion was a success, else False
        """
        try:
            self.remove_person_from_risk_assessments(public_id)
            self.remove_person_from_control_measure_assignments(public_id)
            self.remove_person_from_person_groups(public_id)

            return self.delete_item(public_id)
        except Exception as err:
            raise PersonsManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def update_group_in_persons(self, group_id: int, persons_to_add: list[int], persons_to_delete: list[int]) -> None:
        """
        Syncs a CmdbPersonGroup reference across CmdbPersons during a group update operation

        Args:
            group_id (int): public_id of the CmdbPersonGroup whose membership changed
            persons_to_add (list[int]): public_id's of CmdbPersons that should now reference the group
            persons_to_delete (list[int]): public_id's of CmdbPersons that should no longer reference the group
        """
        self.add_group_to_persons(group_id, persons_to_add)
        self.delete_group_from_persons(group_id, persons_to_delete)


    def add_group_to_persons(self, group_id: int, person_ids: list[int]) -> None:
        """
        Adds a CmdbPersonGroup to the 'groups' of the given CmdbPersons in a single bulk update

        Args:
            group_id (int): public_id of CmdbPersonGroup which should be added
            person_ids (list[int]): public_id's of CmdbPersons where the CmdbPersonGroup should be added
        """
        add_member_to_documents(
            self.dbm,
            self.db_name,
            self.collection,
            PersonKey.GROUPS.value,
            group_id,
            person_ids,
        )


    def delete_group_from_persons(self, group_id: int, persons_ids: list[int] = None) -> None:
        """
        Removes a CmdbPersonGroup from the 'groups' of CmdbPersons in a single bulk '$pull' update

        When persons_ids is provided the pull is restricted to those CmdbPersons, otherwise it is
        applied to every CmdbPerson that references the group

        Args:
            group_id (int): public_id of CmdbPersonGroup which should be removed
            persons_ids (list[int], optional): public_id's of the CmdbPersons to update. Defaults to None
        """
        remove_member_from_documents(
            self.dbm,
            self.db_name,
            self.collection,
            PersonKey.GROUPS.value,
            group_id,
            persons_ids,
        )


    def remove_person_from_person_groups(self, person_id: int) -> None:
        """
        Removes a deleted CmdbPerson from the 'group_members' of every CmdbPersonGroup listing them

        The group side of the two-sided membership. Written straight to the group collection rather
        than through PersonGroupsManager, because a manager must not depend on another manager

        Args:
            person_id (int): public_id of the deleted CmdbPerson
        """
        remove_member_from_documents(
            self.dbm,
            self.db_name,
            CmdbPersonGroup.COLLECTION,
            PersonGroupKey.GROUP_MEMBERS.value,
            person_id,
        )


    def remove_person_from_risk_assessments(self, person_id: int) -> None:
        """
        Removes a CmdbPerson from all IsmsRiskAssessments that reference them

        Three shapes of reference, handled differently:
          - 'risk_assessor_id' can only ever be a person, so it is nulled wherever it matches
          - the polymorphic fields are nulled only where their '_ref_type' sibling says PERSON, so a
            CmdbPersonGroup sharing the public_id is not cleared as well
          - 'interviewed_persons' is a list, so the person is pulled out of it instead of nulled

        Args:
            person_id (int): The public_id of the CmdbPerson to remove from the IsmsRiskAssessments
        """
        self.dbm.update_many(
            IsmsRiskAssessment.COLLECTION,
            self.db_name,
            {RiskAssessmentKey.RISK_ASSESSOR_ID.value: person_id},
            {RiskAssessmentKey.RISK_ASSESSOR_ID.value: None},
        )

        clear_polymorphic_risk_assessment_references(
            self.dbm,
            self.db_name,
            IsmsRiskAssessment.COLLECTION,
            person_id,
            PersonReferenceType.PERSON,
        )

        remove_member_from_documents(
            self.dbm,
            self.db_name,
            IsmsRiskAssessment.COLLECTION,
            RiskAssessmentKey.INTERVIEWED_PERSONS.value,
            person_id,
        )


    def remove_person_from_control_measure_assignments(self, deleted_person_id: int) -> None:
        """
        Nulls the 'responsible_for_implementation_id' of every IsmsControlMeasureAssignment that names
        the deleted CmdbPerson

        Filtered by the field's '_ref_type' sibling, so an assignment whose responsible party is the
        CmdbPersonGroup with the same public_id keeps it

        Args:
            deleted_person_id (int): The public_id of the deleted CmdbPerson
        """
        clear_control_measure_assignment_reference(
            self.dbm,
            self.db_name,
            IsmsControlMeasureAssignment.COLLECTION,
            deleted_person_id,
            PersonReferenceType.PERSON,
        )
