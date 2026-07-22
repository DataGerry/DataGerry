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
<<<<<<< HEAD
=======

>>>>>>> origin/version-3.2
from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation

from cmdb.framework.results import IterationResult

from cmdb.errors.manager.object_relations_manager import (
    OBJECT_RELATIONS_MANAGER_ERRORS,
    ObjectRelationsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)
<<<<<<< HEAD
=======

# Document field names of a CmdbObjectRelation, named here so queries/updates reference a constant
# instead of repeating the literal keys
PUBLIC_ID_FIELD: str = 'public_id'
RELATION_ID_FIELD: str = 'relation_id'
RELATION_PARENT_ID_FIELD: str = 'relation_parent_id'
RELATION_CHILD_ID_FIELD: str = 'relation_child_id'
RELATION_PARENT_TYPE_ID_FIELD: str = 'relation_parent_type_id'
RELATION_CHILD_TYPE_ID_FIELD: str = 'relation_child_type_id'
FIELD_VALUES_FIELD: str = 'field_values'

# Keys of a single ``field_values`` entry. An object-relation field value is a ``name``/``value``
# pair by design (consumed that way across the codebase); it is intentionally NOT a name/value/type
# triple like a CmdbObject field
FIELD_VALUE_NAME_KEY: str = 'name'
FIELD_VALUE_VALUE_KEY: str = 'value'

# Keys of the ``changed_fields`` diff produced by RelationsManager.get_added_and_removed_fields
ADDED_FIELDS_KEY: str = 'added'
REMOVED_FIELDS_KEY: str = 'removed'

# Role an object plays in a relation instance (parent side or child side)
ROLE_PARENT: str = 'parent'
ROLE_CHILD: str = 'child'

# Role-oriented display fields on a CmdbRelation definition, projected into a relation tab
DEF_NAME_PARENT_FIELD: str = 'relation_name_parent'
DEF_NAME_CHILD_FIELD: str = 'relation_name_child'
DEF_ICON_PARENT_FIELD: str = 'relation_icon_parent'
DEF_ICON_CHILD_FIELD: str = 'relation_icon_child'
DEF_COLOR_PARENT_FIELD: str = 'relation_color_parent'
DEF_COLOR_CHILD_FIELD: str = 'relation_color_child'

# Keys of a single relation-tab descriptor returned by build_relation_tabs_pipeline
TAB_RELATION_ID_KEY: str = 'relation_id'
TAB_ROLE_KEY: str = 'role'
TAB_LABEL_KEY: str = 'label'
TAB_ICON_KEY: str = 'icon'
TAB_COLOR_KEY: str = 'color'
TAB_COUNT_KEY: str = 'count'

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
    role_ref = f'$_id.{TAB_ROLE_KEY}'
    is_parent = {'$eq': [role_ref, ROLE_PARENT]}
    definition_ref = f'${_DEFINITION_FIELD}'

    return [
        {'$match': {'$or': [
            {RELATION_PARENT_ID_FIELD: object_id},
            {RELATION_CHILD_ID_FIELD: object_id},
        ]}},
        # An instance places the object on the parent side, the child side, or (self-relation) both
        {'$addFields': {'roles': {'$concatArrays': [
            {'$cond': [{'$eq': [f'${RELATION_PARENT_ID_FIELD}', object_id]}, [ROLE_PARENT], []]},
            {'$cond': [{'$eq': [f'${RELATION_CHILD_ID_FIELD}', object_id]}, [ROLE_CHILD], []]},
        ]}}},
        {'$unwind': '$roles'},
        {'$group': {
            '_id': {TAB_RELATION_ID_KEY: f'${RELATION_ID_FIELD}', TAB_ROLE_KEY: '$roles'},
            TAB_COUNT_KEY: {'$sum': 1},
        }},
        {'$lookup': {
            'from': CmdbRelation.COLLECTION,
            'localField': f'_id.{TAB_RELATION_ID_KEY}',
            'foreignField': PUBLIC_ID_FIELD,
            'as': _DEFINITION_FIELD,
        }},
        # drops groups whose relation definition no longer exists
        {'$unwind': definition_ref},
        {'$project': {
            '_id': 0,
            TAB_RELATION_ID_KEY: f'$_id.{TAB_RELATION_ID_KEY}',
            TAB_ROLE_KEY: role_ref,
            TAB_LABEL_KEY: {'$cond': [is_parent,
                                      f'{definition_ref}.{DEF_NAME_PARENT_FIELD}',
                                      f'{definition_ref}.{DEF_NAME_CHILD_FIELD}']},
            TAB_ICON_KEY: {'$cond': [is_parent,
                                     f'{definition_ref}.{DEF_ICON_PARENT_FIELD}',
                                     f'{definition_ref}.{DEF_ICON_CHILD_FIELD}']},
            TAB_COLOR_KEY: {'$cond': [is_parent,
                                      f'{definition_ref}.{DEF_COLOR_PARENT_FIELD}',
                                      f'{definition_ref}.{DEF_COLOR_CHILD_FIELD}']},
            TAB_COUNT_KEY: 1,
        }},
        # stable order: by relation, parent tab before child tab
        {'$sort': {TAB_RELATION_ID_KEY: 1, TAB_ROLE_KEY: -1}},
    ]
>>>>>>> origin/version-3.2

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
        sort: str = PUBLIC_ID_FIELD,
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
        side_field = RELATION_PARENT_ID_FIELD if role == ROLE_PARENT else RELATION_CHILD_ID_FIELD
        criteria = {RELATION_ID_FIELD: relation_id, side_field: object_id}

        try:
            total = self.count_documents(criteria)
            instances = list(self.find(criteria=criteria, limit=limit, skip=skip, sort=[(sort, order)]))

            return instances, total
        except Exception as err:
            raise ObjectRelationsManagerIterationError(str(err)) from err


    def get_related_relations(self, public_id: int) -> list[dict[str, Any]]:
        """TODO: document"""
        return list(self.find(criteria=self.get_related_relations_query(public_id)))

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
        data[PUBLIC_ID_FIELD] = public_id

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
<<<<<<< HEAD
        """TODO: document"""
        return {
            "$or": [
                {"relation_parent_id": public_id},
                {"relation_child_id": public_id},
            ]
        }

=======
        """
        Builds the query matching every CmdbObjectRelation referencing the given CmdbObject

        Args:
            public_id (int): public_id of the CmdbObject to match as parent or child

        Returns:
            dict[str, Any]: A Mongo ``$or`` query on the parent/child object id fields
        """
        return {
            "$or": [
                {RELATION_PARENT_ID_FIELD: public_id},
                {RELATION_CHILD_ID_FIELD: public_id},
            ]
        }


>>>>>>> origin/version-3.2
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
        type_field = RELATION_PARENT_TYPE_ID_FIELD if is_parent_ids else RELATION_CHILD_TYPE_ID_FIELD

        query: dict[str, Any] = {
            "$and": [
                {RELATION_ID_FIELD: relation_id},
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
        added: list[str] = changed_fields.get(ADDED_FIELDS_KEY, [])
        removed: list[str] = changed_fields.get(REMOVED_FIELDS_KEY, [])

        # Nothing changed: skip the write entirely so unrelated relation edits do not rewrite every
        # dependent CmdbObjectRelation
        if not added and not removed:
            return

        new_field_entries: list[dict[str, Any]] = [
            {FIELD_VALUE_NAME_KEY: name, FIELD_VALUE_VALUE_KEY: None} for name in added
        ]

        # Pipeline update: keep the field values whose name is not removed, then append the new ones
        pipeline: list[dict[str, Any]] = [
            {
                "$set": {
                    FIELD_VALUES_FIELD: {
                        "$concatArrays": [
                            {
                                "$filter": {
                                    "input": {"$ifNull": [f"${FIELD_VALUES_FIELD}", []]},
                                    "as": "fv",
                                    "cond": {
                                        "$not": [{"$in": [f"$$fv.{FIELD_VALUE_NAME_KEY}", removed]}]
                                    },
                                }
                            },
                            new_field_entries,
                        ]
                    }
                }
            }
        ]

        self.update_many({RELATION_ID_FIELD: relation_id}, pipeline, plain=True)
