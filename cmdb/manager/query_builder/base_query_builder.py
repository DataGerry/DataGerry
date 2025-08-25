# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of BaseQueryBuilder
"""
import logging

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.acl.builder import AccessControlQueryBuilder
from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog

from .builder import Builder
from .builder_parameters import BuilderParameters
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               BaseQueryBuilder - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseQueryBuilder(Builder):
    """
    A base class for constructing query objects

    This class provides a foundation for building query structures,
    storing them as a list of dictionaries
    """

    def __init__(self):
        """
        Initializes the BaseQueryBuilder
        """
        self.query: list[dict] = []
        super().__init__()


    def __len__(self) -> int:
        """Get the length of the query"""
        return len(self.query)

# ------------------------------------------------- PUBLIC FUNCTIONS ------------------------------------------------- #

    def build(self,
              builder_params: BuilderParameters,
              user: CmdbUser = None,
              permission: AccessControlPermission = None,
              object_builder_mode: bool = False) -> list[dict]:
        """
        Converts the parameters from the call to a MongoDB aggregation pipeline

        Returns:
            list[dict]: The build query
        """
        self.query = self.__init_query(builder_params.get_criteria(), object_builder_mode)

        if object_builder_mode:
            # TODO: Remove nasty quick hack
            if builder_params.get_sort().startswith('fields'):
                sort_value = builder_params.get_sort()[7:]

                self.query.append({
                    '$addFields': {
                        'order': {
                            '$filter': {
                                'input': '$fields',
                                'as': 'fields',
                                'cond': {'$eq': ['$$fields.name', sort_value]}
                            }
                        }
                    }
                })
                self.query.append({'$sort': {'order': builder_params.get_order()}})
        else:
            self.query.append(self.sort_(builder_params.get_sort(), builder_params.get_order()))

        self.query.append(self.skip_(builder_params.get_skip()))

        if user and permission:
            self.query.extend(AccessControlQueryBuilder().build(user.group_id, permission))

        if builder_params.has_limit():
            self.query.append(self.limit_(builder_params.get_limit()))

        return self.query


    def count(self,
              criteria: dict | list[dict],
              user: CmdbUser = None,
              permission: AccessControlPermission = None) -> list[dict]:
        """
        Count the number of documents

        Args:
            criteria: Filter for documents

        Returns:
            Query with count stages
        """
        self.query = self.__init_query(criteria)

        if user and permission:
            self.query.extend(AccessControlQueryBuilder().build(user.group_id, permission))

        self.query.append(self.count_('total'))

        return self.query

# ------------------------------------------------- HELPER - SECTION ------------------------------------------------- #

    def clear(self) -> None:
        """`Delete` the query content"""
        self.query = None


    def __init_query(self, criteria: dict | list[dict], object_builder_mode: bool = False) -> list[dict]:
        """
        Initialises the query with valid format

        Args:
            criteria (dict | list[dict]): Filter which should be applied

        Returns:
            list[dict]: The initialised query
        """
        self.clear()
        query: list[dict] = []

        if object_builder_mode:
            query = [
                self.lookup_(_from='framework.types', _local='type_id', _foreign='public_id', _as='type'),
                self.unwind_({'path': '$type', 'preserveNullAndEmptyArrays': True}),
                self.match_({'type': {'$ne': None}}),
                self.lookup_(_from='management.users', _local='author_id', _foreign='public_id', _as='author'),
                self.unwind_({'path': '$author', 'preserveNullAndEmptyArrays': True}),
                self.lookup_(_from='management.users', _local='editor_id', _foreign='public_id', _as='editor'),
                self.unwind_({'path': '$editor', 'preserveNullAndEmptyArrays': True}),
            ]

        if isinstance(criteria, dict):
            query.append(self.match_(criteria))

        elif isinstance(criteria, list):
            for pipe in criteria:
                query.append(pipe)

        return query


    def prepare_log_query(self, object_exists: bool = True) -> list[dict]:
        """
        Prepares the query for logs

        Args:
            object_exists (bool): If the referenced object of the log still exists

        Returns:
            list[dict]: the prepared query for object logs
        """
        query = []

        query.append({'$match': {
            'log_type': CmdbObjectLog.__name__,
            'action': {
                '$ne': LogAction.DELETE.value
            }
        }})

        query.append({
            "$lookup": {
                "from": "framework.objects",
                "localField": "object_id",
                "foreignField": "public_id",
                "as": "object"
            }
        })

        query.append({'$unwind': {'path': '$object', 'preserveNullAndEmptyArrays': True}})
        query.append({'$match': {'object': {'$exists': object_exists}}})

        return query
