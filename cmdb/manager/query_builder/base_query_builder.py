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
Implementation of BaseQueryBuilder
"""
from logging import Logger, getLogger

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.acl.builder import AccessControlQueryBuilder
from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog

from .builder import Builder
from .builder_parameters import BuilderParameters
from .query_builder_constants import SortPipeline
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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
              permission: AccessControlPermission = None) -> list[dict]:
        """
        Converts the parameters from the call to a MongoDB aggregation pipeline

        Sort keys that target a value inside the ``fields`` array (``fields.<name>``)
        are handled by projecting the matching element's value into a temporary
        ``_sort_value`` field and sorting on that. All other sort keys go through the
        plain ``$sort`` stage.

        Returns:
            list[dict]: The build query
        """
        self.query = self.__init_query(builder_params.get_criteria())

        self._append_sort_stage(builder_params.get_sort(), builder_params.get_order())

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


    def _append_sort_stage(self, sort_key: str, sort_order: int) -> None:
        """
        Appends the sort stage(s) to ``self.query``

        For keys starting with ``fields.``, the matching element of the ``fields`` array
        is extracted, converted to a lowercased string, and stored in a temporary
        ``_sort_value`` field which is then sorted on (and finally projected away).
        ``public_id`` is used as a stable tiebreaker so pagination remains deterministic
        when two rows share the same sort value

        All other sort keys produce a plain ``$sort`` stage on the given path

        Args:
            sort_key (str): The sort key (e.g. ``"public_id"`` or ``"fields.text-19742"``)
            sort_order (int): ``1`` for ascending, ``-1`` for descending
        """
        if sort_key and sort_key.startswith(SortPipeline.FIELDS_PREFIX):
            field_name = sort_key[len(SortPipeline.FIELDS_PREFIX):]

            self.query.append({
                '$addFields': {
                    SortPipeline.TEMP_KEY: {
                        '$toLower': {
                            '$convert': {
                                'input': {
                                    '$first': {
                                        '$map': {
                                            'input': {
                                                '$filter': {
                                                    'input': '$fields',
                                                    'as': 'f',
                                                    'cond': {'$eq': ['$$f.name', field_name]},
                                                }
                                            },
                                            'as': 'f',
                                            'in': '$$f.value',
                                        }
                                    }
                                },
                                'to': 'string',
                                'onError': '',
                                'onNull': '',
                            }
                        }
                    }
                }
            })
            self.query.append({'$sort': {SortPipeline.TEMP_KEY: sort_order, 'public_id': 1}})
            self.query.append({'$project': {SortPipeline.TEMP_KEY: 0}})
            return

        self.query.append(self.sort_(sort_key, sort_order))


    def __init_query(self, criteria: dict | list[dict]) -> list[dict]:
        """
        Initialises the query with valid format

        Args:
            criteria (dict | list[dict]): Filter which should be applied

        Returns:
            list[dict]: The initialised query
        """
        self.clear()
        query: list[dict] = []

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
