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
This module contains the implementation of the ObjectRelationsManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.object_relation_model import (
    CmdbObjectRelation,
    ObjectRelationKey,
    ObjectRelationFieldValueKey,
    ObjectRelationRole,
    RelationTabKey,
)
from cmdb.models.relation_model import CmdbRelation, RelationKey, RelationDiffKey

from cmdb.framework.results import IterationResult

from cmdb.errors.manager.object_relations_manager import (
    OBJECT_RELATIONS_MANAGER_ERRORS,
    ObjectRelationsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The document keys, the roles and the relation-tab keys are shared with the routes and the
# ObjectRelationLogsManager, so they live with the model (ObjectRelationKey / ObjectRelationRole /
# RelationTabKey in cmdb.models.object_relation_model) instead of being declared per layer

# The keys of the ``changed_fields`` diff and the role-oriented display fields of a CmdbRelation
# definition (projected into a relation tab) belong to the relation document, so they come from
# RelationDiffKey / RelationKey in cmdb.models.relation_model instead of being repeated here

# Temporary field name for the joined relation definition inside the pipeline
_DEFINITION_FIELD: str = 'definition'


def build_relation_tabs_pipeline(object_id: int) -> list[dict[str, Any]]:
    """
    Builds the aggregation pipeline that summarises an object's relations into tab descriptors

    For the given object the pipeline matches every CmdbObjectRelation referencing it, derives the
    role(s) the object plays (parent and/or child - a self-relation counts for both), groups by
    (relation_id, role), counts the instances, joins the CmdbRelation definition and projects the
    role-oriented label / icon / color plus the count. Groups whose relation definition no longer
    exists are dropped (matching the frontend, which skips groups without a definition)

    Args:
        object_id (int): public_id of the CmdbObject whose relation tabs are summarised

    Returns:
        list[dict[str, Any]]: The MongoDB aggregation pipeline
    """
    relation_id_key = RelationTabKey.RELATION_ID.value
    role_key = RelationTabKey.ROLE.value
    parent_id_field = ObjectRelationKey.RELATION_PARENT_ID.value
    child_id_field = ObjectRelationKey.RELATION_CHILD_ID.value

    role_ref = f'$_id.{role_key}'
    is_parent = {'$eq': [role_ref, ObjectRelationRole.PARENT.value]}
    definition_ref = f'${_DEFINITION_FIELD}'

    return [
        {'$match': {'$or': [
            {parent_id_field: object_id},
            {child_id_field: object_id},
        ]}},
        # An instance places the object on the parent side, the child side, or (self-relation) both
        {'$addFields': {'roles': {'$concatArrays': [
            {'$cond': [{'$eq': [f'${parent_id_field}', object_id]}, [ObjectRelationRole.PARENT.value], []]},
            {'$cond': [{'$eq': [f'${child_id_field}', object_id]}, [ObjectRelationRole.CHILD.value], []]},
        ]}}},
        {'$unwind': '$roles'},
        {'$group': {
            '_id': {relation_id_key: f'${ObjectRelationKey.RELATION_ID.value}', role_key: '$roles'},
            RelationTabKey.COUNT.value: {'$sum': 1},
        }},
        {'$lookup': {
            'from': CmdbRelation.COLLECTION,
            'localField': f'_id.{relation_id_key}',
            'foreignField': ObjectRelationKey.PUBLIC_ID.value,
            'as': _DEFINITION_FIELD,
        }},
        # drops groups whose relation definition no longer exists
        {'$unwind': definition_ref},
        {'$project': {
            '_id': 0,
            relation_id_key: f'$_id.{relation_id_key}',
            role_key: role_ref,
            RelationTabKey.LABEL.value: {'$cond': [is_parent,
                                                   f'{definition_ref}.{RelationKey.RELATION_NAME_PARENT.value}',
                                                   f'{definition_ref}.{RelationKey.RELATION_NAME_CHILD.value}']},
            RelationTabKey.ICON.value: {'$cond': [is_parent,
                                                  f'{definition_ref}.{RelationKey.RELATION_ICON_PARENT.value}',
                                                  f'{definition_ref}.{RelationKey.RELATION_ICON_CHILD.value}']},
            RelationTabKey.COLOR.value: {'$cond': [is_parent,
                                                   f'{definition_ref}.{RelationKey.RELATION_COLOR_PARENT.value}',
                                                   f'{definition_ref}.{RelationKey.RELATION_COLOR_CHILD.value}']},
            RelationTabKey.COUNT.value: 1,
        }},
        # stable order: by relation, parent tab before child tab
        {'$sort': {relation_id_key: 1, role_key: -1}},
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                            ObjectRelationsManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectRelationsManager(GenericManager):
    """
    The ObjectRelationsManager handles the interaction between the CmdbObjectRelations-API and the database

    `Extends`: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the ObjectRelationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE. Defaults to None

        Raises:
            ObjectRelationsManagerInitError: If the ObjectRelationsManager could not be initialised
        """
        super().__init__(dbm, CmdbObjectRelation, OBJECT_RELATIONS_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_object_relation(self, object_relation: dict[str, Any] | CmdbObjectRelation) -> int:
        """
        Insert a CmdbObjectRelation into the database

        Args:
            object_relation (dict[str, Any] | CmdbObjectRelation): Raw data or model instance of the
                                                                   CmdbObjectRelation

        Raises:
            ObjectRelationsManagerInsertError: When a CmdbObjectRelation could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbObjectRelation
        """
        return self.insert_item(object_relation)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_object_relation(self, public_id: int) -> dict[str, Any] | None:
        """
        Retrieves a CmdbObjectRelation from the database

        Args:
            public_id (int): public_id of the CmdbObjectRelation

        Raises:
            ObjectRelationsManagerGetError: When a CmdbObjectRelation could not be retrieved

        Returns:
            dict[str, Any] | None: Dict representation of the CmdbObjectRelation if it exists else None
        """
        return self.get_item(public_id, as_dict=True)


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbObjectRelation]:
        """
        Retrieves multiple CmdbObjectRelations

        Args:
            builder_params (BuilderParameters): Filter for which CmdbObjectRelations should be retrieved

        Raises:
            ObjectRelationsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbObjectRelation]: All CmdbObjectRelations matching the filter
        """
        return self.iterate_items(builder_params)


    def get_related_relations(self, public_id: int) -> list[dict[str, Any]]:
        """
        Retrieves all CmdbObjectRelations referencing the given CmdbObject as parent or child

        Args:
            public_id (int): public_id of the CmdbObject whose CmdbObjectRelations are requested

        Returns:
            list[dict[str, Any]]: All CmdbObjectRelations where the CmdbObject is the parent or the child
        """
        return list(self.find(criteria=self.get_related_relations_query(public_id)))


    def get_relation_tabs(self, object_id: int) -> list[dict[str, Any]]:
        """
        Summarises the object's relations into tab descriptors without loading any instances

        Each descriptor is one (relation_id, role) group with the role-oriented label / icon / color
        and the instance count - enough to render the relation tabs. Computed in a single aggregation

        Args:
            object_id (int): public_id of the CmdbObject whose relation tabs are requested

        Raises:
            ObjectRelationsManagerIterationError: When the aggregation fails

        Returns:
            list[dict[str, Any]]: One descriptor per (relation_id, role) group
        """
        try:
            return list(self.aggregate(build_relation_tabs_pipeline(object_id)))
        except Exception as err:
            raise ObjectRelationsManagerIterationError(str(err)) from err


    def get_relation_tab_instances(
        self,
        object_id: int,
        relation_id: int,
        role: str,
        limit: int = 0,
        skip: int = 0,
        sort: str = ObjectRelationKey.PUBLIC_ID.value,
        order: int = 1,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Retrieves one page of a relation tab's instances plus the group's total

        A tab is identified by (relation_id, role): role=parent selects instances where the object is
        the parent, role=child where it is the child. The total is the raw count of the group (so it
        matches the tab badge and drives pagination); only the requested page is materialised

        Args:
            object_id (int): public_id of the CmdbObject whose relations are listed
            relation_id (int): public_id of the CmdbRelation definition (the tab's relation)
            role (str): 'parent' or 'child' - the side the object plays in this tab
            limit (int): Page size (0 = no limit). Defaults to 0
            skip (int): Number of documents to skip. Defaults to 0
            sort (str): Field to sort by. Defaults to public_id
            order (int): Sort direction, 1 ascending / -1 descending. Defaults to 1

        Raises:
            ObjectRelationsManagerIterationError: When the query fails

        Returns:
            tuple[list[dict[str, Any]], int]: (the page's object-relation documents, total in group)
        """
        side_field = (ObjectRelationKey.RELATION_PARENT_ID.value if role == ObjectRelationRole.PARENT
                      else ObjectRelationKey.RELATION_CHILD_ID.value)
        criteria = {ObjectRelationKey.RELATION_ID.value: relation_id, side_field: object_id}

        try:
            total = self.count_documents(criteria)
            instances = list(self.find(criteria=criteria, limit=limit, skip=skip, sort=[(sort, order)]))

            return instances, total
        except Exception as err:
            raise ObjectRelationsManagerIterationError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_object_relation(self, public_id: int, data: dict[str, Any] | CmdbObjectRelation) -> None:
        """
        Updates a CmdbObjectRelation in the database

        The document identity is pinned to ``public_id`` so a payload ``public_id`` can never rewrite
        the document's id.

        Args:
            public_id (int): public_id of the CmdbObjectRelation which should be updated
            data (dict[str, Any] | CmdbObjectRelation): The new values for the CmdbObjectRelation

        Raises:
            ObjectRelationsManagerUpdateError: When the update operation fails
        """
        if isinstance(data, CmdbObjectRelation):
            data = CmdbObjectRelation.to_json(data)

        # Pin the identity: a payload public_id can never rewrite the document's id
        data[ObjectRelationKey.PUBLIC_ID.value] = public_id

        self.update_item(public_id, data)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_object_relation(self, public_id: int) -> bool:
        """
        Deletes a CmdbObjectRelation from the database

        Args:
            public_id (int): public_id of the CmdbObjectRelation which should be deleted

        Raises:
            ObjectRelationsManagerDeleteError: When the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        return self.delete_item(public_id)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_related_relations_query(self, public_id: int) -> dict[str, Any]:
        """
        Builds the query matching every CmdbObjectRelation referencing the given CmdbObject

        Args:
            public_id (int): public_id of the CmdbObject to match as parent or child

        Returns:
            dict[str, Any]: A Mongo ``$or`` query on the parent/child object id fields
        """
        return {
            "$or": [
                {ObjectRelationKey.RELATION_PARENT_ID.value: public_id},
                {ObjectRelationKey.RELATION_CHILD_ID.value: public_id},
            ]
        }


    def delete_invalidated_object_relations(
            self,
            relation_id: int,
            invalid_ids: list[int],
            is_parent_ids: bool) -> None:
        """
        Deletes invalid CmdbObjectRelations based on the given `relation_id` and `invalid_ids`

        This method checks whether the invalid IDs are related to the parent or child types
        of the given CmdbRelation, then deletes every matching CmdbObjectRelation in a single
        server-side operation.

        Args:
            relation_id (int): The public_id of the CmdbRelation for which invalid
                               CmdbObjectRelations should be deleted
            invalid_ids (list[int]): A list of IDs (either parent or child) that should be invalidated
            is_parent_ids (bool): A flag indicating whether the invalid IDs belong to parent type relations
                                  (True) or child type relations (False)
        """
        type_field = (ObjectRelationKey.RELATION_PARENT_TYPE_ID.value if is_parent_ids
                      else ObjectRelationKey.RELATION_CHILD_TYPE_ID.value)

        query: dict[str, Any] = {
            "$and": [
                {ObjectRelationKey.RELATION_ID.value: relation_id},
                {type_field: {"$in": invalid_ids}},
            ]
        }

        # Single server-side delete instead of fetch-then-loop (avoids an N+1 delete walk)
        self.delete_many(query)


    def update_changed_fields(self, relation_id: int, changed_fields: dict[str, list[str]]) -> None:
        """
        Updates all CmdbObjectRelations that reference the given CmdbRelation

        - **Removes** any ``field_values`` whose name is in ``changed_fields['removed']``
        - **Adds** new ``field_values`` (with an empty value) for each name in ``changed_fields['added']``

        Both edits are applied in a single server-side ``update_many`` aggregation pipeline, so no
        documents are loaded into Python and no per-document write loop is issued.

        Args:
            relation_id (int): The public_id of the CmdbRelation whose fields were changed
            changed_fields (dict[str, list[str]]): A dictionary with two keys:
                - "added" (list[str]): Field names that were newly introduced
                - "removed" (list[str]): Field names that should be removed
        """
        added: list[str] = changed_fields.get(RelationDiffKey.ADDED.value, [])
        removed: list[str] = changed_fields.get(RelationDiffKey.REMOVED.value, [])

        # Nothing changed: skip the write entirely so unrelated relation edits do not rewrite every
        # dependent CmdbObjectRelation
        if not added and not removed:
            return

        name_key = ObjectRelationFieldValueKey.NAME.value
        field_values_field = ObjectRelationKey.FIELD_VALUES.value

        new_field_entries: list[dict[str, Any]] = [
            {name_key: name, ObjectRelationFieldValueKey.VALUE.value: None} for name in added
        ]

        # Pipeline update: keep the field values whose name is not removed, then append the new ones
        pipeline: list[dict[str, Any]] = [
            {
                "$set": {
                    field_values_field: {
                        "$concatArrays": [
                            {
                                "$filter": {
                                    "input": {"$ifNull": [f"${field_values_field}", []]},
                                    "as": "fv",
                                    "cond": {
                                        "$not": [{"$in": [f"$$fv.{name_key}", removed]}]
                                    },
                                }
                            },
                            new_field_entries,
                        ]
                    }
                }
            }
        ]

        self.update_many({ObjectRelationKey.RELATION_ID.value: relation_id}, pipeline, plain=True)
