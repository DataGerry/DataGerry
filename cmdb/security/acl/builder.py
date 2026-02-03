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
Implementation of LookedAccessControlQueryBuilder
"""
from cmdb.manager.query_builder.pipeline_builder import PipelineBuilder
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #


class LookedAccessControlQueryBuilder(PipelineBuilder):
    """
    Query builder for access control on *looked* (nested) objects in MongoDB aggregation pipelines.
    
    This builder is used when the type information is nested inside a sub-object (e.g., `object.type_id`).
    """

    def __init__(self, pipeline: list[dict] = None):
        """
        Initialize the LookedAccessControlQueryBuilder

        Args:
            pipeline (list[dict], optional): An optional initial aggregation pipeline. Defaults to None
        """
        super().__init__(pipeline=pipeline)


    #TODO: REFACTOR-FIX (same method in AccessControlQueryBuilder)
    def build(self, group_id: int, permission: AccessControlPermission, *args, **kwargs) -> list[dict]:
        """
        Build the access control aggregation pipeline for nested objects

        This builds a pipeline that:
        1. Looks up type information for nested object documents
        2. Unwinds the type field
        3. Matches documents based on access control rules

        Args:
            group_id (int): The group ID for which to validate access
            permission (AccessControlPermission): The required permission to filter by
            *args: Additional positional arguments (currently unused)
            **kwargs: Additional keyword arguments (currently unused)

        Returns:
            list[dict]: The complete aggregation pipeline as a list of stages
        """
        self.clear()
        self.add_pipe(self._lookup_types())
        self.add_pipe(self._unwind_types())
        self.add_pipe(self._match_acl(group_id, permission))
        return self.pipeline

    # REFACTOR-FIX (same method in AccessControlQueryBuilder)
    def _lookup_types(self) -> dict:
        """
        Create a `$lookup` aggregation stage to join the `framework.types` collection

        Joins using the `object.type_id` field from the current collection

        Returns:
            dict: A `$lookup` stage for the aggregation pipeline
        """
        return {
            '$lookup': {
                'from': 'framework.types',
                'localField': 'object.type_id',  # Field in the current collection
                'foreignField': 'public_id',     # Field in the 'framework.types' collection
                'as': 'type'
            }
        }


    # REFACTOR-FIX (same method in AccessControlQueryBuilder)
    def _unwind_types(self) -> dict:
        """
        Create an `$unwind` aggregation stage for the `type` field

        Returns:
            dict: An `$unwind` stage for the aggregation pipeline
        """
        unwind = self.unwind_({'path': '$type', 'preserveNullAndEmptyArrays': True})

        return unwind


    # REFACTOR-FIX (same method in AccessControlQueryBuilder)
    def _match_acl(self, group_id: int, permission: AccessControlPermission) -> dict:
        """
        Create a `$match` aggregation stage based on access control logic

        The match criteria:
        - Allow documents where `type.acl` does not exist
        - Allow documents where `type.acl.activated` is False
        - Allow documents where the group ID has all the required permissions

        Args:
            group_id (int): The group ID to filter access by
            permission (AccessControlPermission): The permission required

        Returns:
            dict: A `$match` stage for the aggregation pipeline
        """
        return self.match_(
            self.or_([
                self.exists_('type.acl', False),
                {'type.acl.activated': False},
                self.and_([
                    self.exists_(f'type.acl.groups.includes.{group_id}', True),
                    {f'type.acl.groups.includes.{group_id}': {'$all': [permission.value]}}
                ])
            ])
        )


#TODO: CLASS-FIX (Move to manager query builder)
class AccessControlQueryBuilder(PipelineBuilder):
    """
    Query builder for applying access control restrictions in MongoDB aggregation pipelines.
    
    This builder ensures that objects in aggregation results are filtered based on the access control lists (ACLs)
    associated with their types.
    """


    def __init__(self, pipeline: list[dict] = None):
        """
        Initialize the AccessControlQueryBuilder

        Args:
            pipeline (list[dict], optional): An optional initial aggregation pipeline. Defaults to None
        """
        super().__init__(pipeline=pipeline)


    #TODO: REFACTOR-FIX (same method in LookedAccessControlQueryBuilder)
    def build(self, group_id: int, permission: AccessControlPermission, *args, **kwargs) -> list[dict]:
        """
        Build the access control aggregation pipeline

        This builds a pipeline that:
        1. Looks up type information for documents
        2. Unwinds the type field
        3. Matches documents based on access control rules

        Args:
            group_id (int): The group ID for which to validate access
            permission (AccessControlPermission): The required permission to filter by
            *args: Additional positional arguments (currently unused)
            **kwargs: Additional keyword arguments (currently unused)

        Returns:
            list[dict]: The complete aggregation pipeline as a list of stages
        """
        self.clear()
        self.add_pipe(self._lookup_types())
        self.add_pipe(self._unwind_types())
        self.add_pipe(self._match_acl(group_id, permission))

        return self.pipeline


    #TODO: REFACTOR-FIX (same method in LookedAccessControlQueryBuilder)
    def _lookup_types(self) -> dict:
        """
        Create a `$lookup` aggregation stage to join the `framework.types` collection

        Joins the current collection with `framework.types` based on `type_id` and `public_id`

        Returns:
            dict: A `$lookup` stage for the aggregation pipeline
        """
        return {
            '$lookup': {
                'from': 'framework.types',
                'localField': 'type_id',    # Field from the current collection
                'foreignField': 'public_id', # Field from the 'framework.types' collection
                'as': 'type'
            }
        }


    #TODO: REFACTOR-FIX (same method in LookedAccessControlQueryBuilder)
    def _unwind_types(self) -> dict:
        """
        Create an `$unwind` aggregation stage for the `type` field

        Returns:
            dict: An `$unwind` stage for the aggregation pipeline
        """
        unwind = self.unwind_({'path': '$type', 'preserveNullAndEmptyArrays': True})

        return unwind


    #TODO: REFACTOR-FIX (same method in LookedAccessControlQueryBuilder)
    def _match_acl(self, group_id: int, permission: AccessControlPermission) -> dict:
        """
        Create a `$match` aggregation stage based on access control logic

        The match criteria:
        - Allow documents where `type.acl` does not exist
        - Allow documents where `type.acl.activated` is False
        - Allow documents where the group ID has all the required permissions

        Args:
            group_id (int): The group ID to filter access by
            permission (AccessControlPermission): The permission required

        Returns:
            dict: A `$match` stage for the aggregation pipeline
        """
        return self.match_(
            self.or_([
                self.exists_('type.acl', False),
                {'type.acl.activated': False},
                self.and_([
                    self.exists_(f'type.acl.groups.includes.{group_id}', True),
                    {f'type.acl.groups.includes.{group_id}': {'$all': [permission.value]}}
                ])
            ])
        )
