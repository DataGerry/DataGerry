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
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
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
        Updates a CmdbPerson in CmdbPersonGroups during an update operation

        Args:
            group_id (int): public_id of CmdbPersonGroup which should be updated
            persons_to_add (list[int]): public_id's of CmdbPersons where the CmdbPersonGroup should be added
            persons_to_delete (list[int]): list of CmdbPerson public_id's which should be deleted
        """
        self.add_group_to_persons(group_id, persons_to_add)
        self.delete_group_from_persons(group_id, persons_to_delete)


    def add_group_to_persons(self, group_id: int, person_ids: list[int]) -> None:
        """
        Adds a CmdbPerson to the given CmdbPersonGroups

        Args:
            group_id (int): public_id of CmdbPersonGroup which should be added
            person_ids (list[int]): public_id's of CmdbPersons where the CmdbPersonGroup should be added
        """
        for person_id in person_ids:
            cur_person = self.get_item(person_id, as_dict=True)

            if cur_person:
                current_groups: list = cur_person.get('groups', [])

                if group_id not in current_groups:
                    current_groups.append(group_id)
                    cur_person['groups'] = current_groups
                    self.update_item(person_id, cur_person)


    def delete_group_from_persons(self, group_id: int, persons_ids: list[int] = None) -> None:
        """
        Removes a CmdbPersonGroup from all CmdbPersons

        Args:
            group_id (int): public_id of CmdbPersonGroup which should be deleted
            persons_ids (list[int], optional): list of CmdbPerson public_id's which should be deleted
        """
        if persons_ids is not None:
            # Use provided group IDs
            persons_with_group = [self.get_item(person_id) for person_id in persons_ids]
        else:
            # Otherwise, find all groups containing the person
            persons_with_group = self.find_all(criteria={'groups': group_id})

        for person in persons_with_group:
            if person is None:
                continue  # Skip if person wasn't found

            person_id = person['public_id']
            current_groups: list = person.get('groups', [])

            if group_id in current_groups:
                current_groups.remove(group_id)
                person['groups'] = current_groups
                self.update_item(person_id, person)


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
        # Query to find RiskAssessments where the person is referenced
        query = {
            '$or': [
                {'risk_assessor_id': person_id},
                {'interviewed_persons': person_id},
                {'risk_owner_id': person_id},
                {'responsible_persons_id': person_id},
                {'auditor_id': person_id}
            ]
        }

        # Find all RiskAssessments where the person_id is referenced and then update them properly
        risk_assessments = self.dbm.find(collection=IsmsRiskAssessment.COLLECTION, db_name=self.db_name, filter=query)

        risk_assessment: dict
        for risk_assessment in risk_assessments:
            update_fields = {}

            # Handle the 'risk_assessor_id' field (since it can only be a Person)
            if risk_assessment.get('risk_assessor_id') == person_id:
                update_fields['risk_assessor_id'] = None

            # Handle the 'risk_owner_id' field (only if it's a Person)
            if risk_assessment.get('risk_owner_id') == person_id:
                ref_type = risk_assessment.get('risk_owner_id_ref_type', '')
                if ref_type == PersonReferenceType.PERSON:
                    update_fields['risk_owner_id'] = None

            # Handle the 'responsible_persons_id' field (only if it's a Person)
            if risk_assessment.get('responsible_persons_id') == person_id:
                ref_type = risk_assessment.get('responsible_persons_id_ref_type', '')
                if ref_type == PersonReferenceType.PERSON:
                    update_fields['responsible_persons_id'] = None

            # Handle the 'auditor_id' field (only if it's a Person)
            if risk_assessment.get('auditor_id') == person_id:
                ref_type = risk_assessment.get('auditor_id_ref_type', '')
                if ref_type == PersonReferenceType.PERSON:
                    update_fields['auditor_id'] = None

            # Handle the 'interviewed_persons' field (Remove from list, not set to None)
            if person_id in risk_assessment.get('interviewed_persons', []):
                pull_update = {
                    'interviewed_persons': person_id
                }
                # Perform the update with $pull for 'interviewed_persons'
                self.dbm.update(
                    IsmsRiskAssessment.COLLECTION,
                    self.db_name,
                    {"public_id": risk_assessment["public_id"]},
                    {"$pull": pull_update},
                    plain=True
                )

            # If there are any updates to make, update this RiskAssessment
            if update_fields:
                self.dbm.update(
                    IsmsRiskAssessment.COLLECTION,
                    self.db_name,
                    {"public_id": risk_assessment["public_id"]},
                    {"$set": update_fields},
                    plain=True
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
