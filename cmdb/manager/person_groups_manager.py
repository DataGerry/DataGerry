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
<<<<<<< HEAD
=======
from typing import Any
>>>>>>> origin/version-3.2

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
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
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
        Adds a CmdbPerson to the 'group_members' of the given CmdbPersonGroups in a single bulk update

        Uses '$addToSet' so the person is only added where they are not already a member, matching the
        previous per-group duplicate check without loading each CmdbPersonGroup first.

        Args:
            person_id (int): public_id of CmdbPerson which should be added
            group_ids (list[int]): public_id's of CmdbPersonGroups where the CmdbPerson should be added
        """
        if not group_ids:
            return

        self.dbm.update_many(
            self.collection,
            self.db_name,
            {'public_id': {'$in': list(group_ids)}},
            {'group_members': person_id},
            add_to_set=True,
        )


    def delete_person_from_groups(self, person_id: int, groups_ids: list[int] = None) -> None:
        """
        Removes a CmdbPerson from the 'group_members' of CmdbPersonGroups in a single bulk '$pull' update

        When groups_ids is provided the pull is restricted to those CmdbPersonGroups, otherwise it is
        applied to every CmdbPersonGroup that lists the person as a member.

        Args:
            person_id (int): public_id of CmdbPerson which should be removed
            groups_ids (list[int], optional): public_id's of the CmdbPersonGroups to update. Defaults to None
        """
        criteria: dict[str, Any] = {'group_members': person_id}

        if groups_ids is not None:
            criteria['public_id'] = {'$in': list(groups_ids)}

        self.dbm.update_many_pull(
            self.collection,
            self.db_name,
            criteria,
            {'group_members': person_id},
        )


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
        # Each field is polymorphic; null it only where it references the deleted PersonGroup
        for field in ('responsible_persons_id', 'risk_owner_id', 'auditor_id'):
            self.dbm.update_many(
                IsmsRiskAssessment.COLLECTION,
                self.db_name,
                {field: deleted_person_group_id, f'{field}_ref_type': PersonReferenceType.PERSON_GROUP},
                {field: None},
            )
