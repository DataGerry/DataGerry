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
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType

from cmdb.errors.manager.person_groups_manager import PERSON_GROUPS_MANAGER_ERRORS
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
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, CmdbPersonGroup, PERSON_GROUPS_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes a CmdbPersonGroup and cleans all affected collections from it

        Args:
            public_id (int): public_id of CmdbPersonGroup which should be deleted

        Returns:
            bool: True if deletion was a success, else False
        """
        self.remove_person_group_from_risk_assessments(public_id)
        self.remove_person_group_from_control_measure_assignments(public_id)

        return self.delete_item(public_id)

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
        Adds a CmdbPerson to the given CmdbPersonGroups

        Args:
            person_id (int): public_id of CmdbPerson which should be added
            group_ids (list[int]): public_id's of CmdbPersonGroups where the CmdbPerson should be added
        """
        for group_id in group_ids:
            cur_group = self.get_item(group_id, as_dict=True)

            if cur_group:
                current_members: list = cur_group.get('group_members', [])

                if person_id not in current_members:
                    current_members.append(person_id)
                    cur_group['group_members'] = current_members
                    self.update_item(group_id, cur_group)


    def delete_person_from_groups(self, person_id: int, groups_ids: list[int] = None) -> None:
        """
        Removes a CmdbPerson from all CmdbPersonGroups

        Args:
            person_id (int): public_id of CmdbPerson which should be deleted
            groups_ids (list[int], optional): list of CmdbPersonGroup public_id's which should be deleted
        """
        if groups_ids is not None:
            # Use provided group IDs
            groups_with_person = [self.get_item(group_id) for group_id in groups_ids]
        else:
            # Otherwise, find all groups containing the person
            groups_with_person = self.find_all(criteria={'group_members': person_id})

        for group in groups_with_person:
            if group is None:
                continue  # Skip if group wasn't found

            group_id = group['public_id']
            current_members: list = group.get('group_members', [])

            if person_id in current_members:
                current_members.remove(person_id)
                group['group_members'] = current_members
                self.update_item(group_id, group)


    def remove_person_group_from_control_measure_assignments(self, deleted_person_group_id: int) -> None:
        """
        Deletes a CmdbPersonGroup from all ControlMeasureAssignments by replacing the 
        'responsible_for_implementation_id' field based on the person group's reference type.
        
        If 'responsible_for_implementation_id_ref_type' is 'PERSON_GROUP' and the 
        'responsible_for_implementation_id' matches the deleted person group's ID,
        it sets the 'responsible_for_implementation_id' to None.
        
        Args:
            deleted_person_group_id (int): The public_id of the deleted CmdbPersonGroup
        """
        # Query to find all ControlMeasureAssignments where the responsible_for_implementation_id
        # matches the deleted person group's ID, only if the ref_type is PERSON_GROUP.
        query = {
            '$and': [
                {'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON_GROUP},
                {'responsible_for_implementation_id': deleted_person_group_id}
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


    def remove_person_group_from_risk_assessments(self, deleted_person_group_id: int) -> None:
        """
        Deletes a CmdbPersonGroup from all RiskAssessments by replacing the corresponding
        fields with None where they reference the deleted PersonGroup's public_id.
        
        If 'responsible_persons_id_ref_type', 'auditor_id_ref_type', or 'risk_owner_id_ref_type'
        is 'PERSON_GROUP' and their respective IDs match the deleted person group's ID,
        it sets those fields to None
        
        Args:
            deleted_person_group_id (int): The public_id of the deleted CmdbPersonGroup
        """
        # Query to retrieve all RiskAssessments where any of the relevant fields
        # reference the deleted PersonGroup's ID
        query = {
            '$or': [
                {'responsible_persons_id_ref_type': PersonReferenceType.PERSON_GROUP},
                {'risk_owner_id_ref_type': PersonReferenceType.PERSON_GROUP},
                {'auditor_id_ref_type': PersonReferenceType.PERSON_GROUP}
            ]
        }

        # Retrieve all matching RiskAssessments
        risk_assessments = self.dbm.find(IsmsRiskAssessment.COLLECTION, self.db_name, query)

        # Loop through each RiskAssessment to check and update relevant fields
        risk_assessment: dict
        for risk_assessment in risk_assessments:
            update_fields = {}

            # Check responsible_persons_id field
            if (risk_assessment.get('responsible_persons_id_ref_type') == PersonReferenceType.PERSON_GROUP and
                risk_assessment.get('responsible_persons_id') == deleted_person_group_id):
                update_fields['responsible_persons_id'] = None

            # Check risk_owner_id field
            if (risk_assessment.get('risk_owner_id_ref_type') == PersonReferenceType.PERSON_GROUP and
                risk_assessment.get('risk_owner_id') == deleted_person_group_id):
                update_fields['risk_owner_id'] = None

            # Check auditor_id field
            if (risk_assessment.get('auditor_id_ref_type') == PersonReferenceType.PERSON_GROUP and
                risk_assessment.get('auditor_id') == deleted_person_group_id):
                update_fields['auditor_id'] = None

            # Perform update if any fields need to be updated
            if update_fields:
                self.dbm.update_many(
                    IsmsRiskAssessment.COLLECTION,
                    self.db_name,
                    {'public_id': risk_assessment['public_id']},
                    {'$set': update_fields},
                    plain=True
                )
