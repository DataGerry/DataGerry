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
"""
from logging import Logger, getLogger
<<<<<<< HEAD
=======
from typing import Any
>>>>>>> origin/version-3.2

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.person_model import CmdbPerson
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType

from cmdb.errors.manager.persons_manager import PERSONS_MANAGER_ERRORS
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

        Args:
            public_id (int): public_id of CmdbPerson which should be deleted

        Returns:
            bool: True if deletion was a success, else False
        """
        self.remove_person_from_risk_assessments(public_id)
        self.remove_person_from_control_measure_assignments(public_id)

        return self.delete_item(public_id)

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

        Uses '$addToSet' so the group is only added where it is not already present, matching the
        previous per-person duplicate check without loading each CmdbPerson first.

        Args:
            group_id (int): public_id of CmdbPersonGroup which should be added
            person_ids (list[int]): public_id's of CmdbPersons where the CmdbPersonGroup should be added
        """
        if not person_ids:
            return

        self.dbm.update_many(
            self.collection,
            self.db_name,
            {'public_id': {'$in': list(person_ids)}},
            {'groups': group_id},
            add_to_set=True,
        )


    def delete_group_from_persons(self, group_id: int, persons_ids: list[int] = None) -> None:
        """
        Removes a CmdbPersonGroup from the 'groups' of CmdbPersons in a single bulk '$pull' update

        When persons_ids is provided the pull is restricted to those CmdbPersons, otherwise it is
        applied to every CmdbPerson that references the group.

        Args:
            group_id (int): public_id of CmdbPersonGroup which should be removed
            persons_ids (list[int], optional): public_id's of the CmdbPersons to update. Defaults to None
        """
        criteria: dict[str, Any] = {'groups': group_id}

        if persons_ids is not None:
            criteria['public_id'] = {'$in': list(persons_ids)}

        self.dbm.update_many_pull(
            self.collection,
            self.db_name,
            criteria,
            {'groups': group_id},
        )


    def remove_person_from_risk_assessments(self, person_id: int) -> None:
        """
        Removes a CmdbPerson from all RiskAssessments that reference this person.
        
        This function will go through all RiskAssessments and update the relevant fields 
        where the person is referenced. If the person is in the `interviewed_persons` list, 
        they will be removed from the list. Otherwise, the person's reference in other fields 
        will be set to None, but only if the field is referencing a CmdbPerson.

        Args:
            person_id (int): The public_id of the CmdbPerson to remove from RiskAssessments
        """
        # 'risk_assessor_id' can only ever reference a Person, so it is nulled wherever it matches
        self.dbm.update_many(
            IsmsRiskAssessment.COLLECTION,
            self.db_name,
            {'risk_assessor_id': person_id},
            {'risk_assessor_id': None},
        )

        # The remaining scalar fields are polymorphic; only null them where they reference a Person
        for field in ('risk_owner_id', 'responsible_persons_id', 'auditor_id'):
            self.dbm.update_many(
                IsmsRiskAssessment.COLLECTION,
                self.db_name,
                {field: person_id, f'{field}_ref_type': PersonReferenceType.PERSON},
                {field: None},
            )

        # 'interviewed_persons' is a Person list, so the person is pulled out of it instead of nulled
        self.dbm.update_many_pull(
            IsmsRiskAssessment.COLLECTION,
            self.db_name,
            {'interviewed_persons': person_id},
            {'interviewed_persons': person_id},
        )


    def remove_person_from_control_measure_assignments(self, deleted_person_id: int) -> None:
        """
        Deletes a CmdbPerson from all ControlMeasureAssignments by replacing the 
        'responsible_for_implementation_id' field based on the person's reference type.
        
        If 'responsible_for_implementation_id_ref_type' is 'PERSON' and the 
        'responsible_for_implementation_id' matches the deleted person's ID,
        it sets the 'responsible_for_implementation_id' to None.
        
        Args:
            deleted_person_id (int): The public_id of the deleted CmdbPerson
        """
        # Query to find all ControlMeasureAssignments where the responsible_for_implementation_id
        # matches the deleted person's ID, only if the ref_type is PERSON.
        query = {
            '$and': [
                {'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON},
                {'responsible_for_implementation_id': deleted_person_id}
            ]
        }

        # Perform the update using the update_many function
        self.dbm.update_many(
            IsmsControlMeasureAssignment.COLLECTION,
            self.db_name,
            query,
            {"$set": {'responsible_for_implementation_id': None}},
            plain=True
        )
