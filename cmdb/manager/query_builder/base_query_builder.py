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
from typing import Any

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.acl.builder import build_acl_pipeline
from cmdb.models.user_model import CmdbUser

from cmdb.utils import Builder
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

    def __init__(self) -> None:
        """
        Initializes the BaseQueryBuilder
        """
        self.query: list[dict[str, Any]] = []
        super().__init__()


    def __len__(self) -> int:
        """Get the length of the query"""
        return len(self.query)

# ------------------------------------------------- PUBLIC FUNCTIONS ------------------------------------------------- #

    def build(self,
              builder_params: BuilderParameters,
              user: CmdbUser | None = None,
              permission: AccessControlPermission | None = None) -> list[dict[str, Any]]:
        """
        Converts the parameters from the call to a MongoDB aggregation pipeline

        Sort keys that target a value inside the ``fields`` array (``fields.<name>``)
        are handled by projecting the matching element's value into a temporary
        ``_sort_value`` field and sorting on that. All other sort keys go through the
        plain ``$sort`` stage.

        The access-control stages are appended directly after the criteria, BEFORE sorting and
        paginating. That order is what makes pagination correct for a restricted user: skipping
        first would skip documents out of the unfiltered set, so a page could silently omit rows
        the user is allowed to see. Filtering first also shrinks the set that has to be sorted.

        Returns:
            list[dict[str, Any]]: The build query
        """
        self.query = self.__init_query(builder_params.get_criteria())

        if user and permission:
            self.query.extend(build_acl_pipeline(user, permission))

        self._append_sort_stage(builder_params.get_sort(), builder_params.get_order())

        self.query.append(self.skip_(builder_params.get_skip()))

        if builder_params.has_limit():
            self.query.append(self.limit_(builder_params.get_limit()))

        return self.query


    def count(self,
              criteria: dict[str, Any] | list[dict[str, Any]],
              user: CmdbUser | None = None,
              permission: AccessControlPermission | None = None) -> list[dict[str, Any]]:
        """
        Count the number of documents

        Args:
            criteria (dict[str, Any] | list[dict[str, Any]]): Filter for documents
            user (CmdbUser | None): The user the ACL stages are built for
            permission (AccessControlPermission | None): The permission the ACL stages check

        Returns:
            list[dict[str, Any]]: Query with count stages
        """
        self.query = self.__init_query(criteria)

        if user and permission:
            self.query.extend(build_acl_pipeline(user, permission))

        self.query.append(self.count_('total'))

        return self.query

# ------------------------------------------------- HELPER - SECTION ------------------------------------------------- #

    def clear(self) -> None:
        """
        Resets the query to an empty stage list, the state the constructor starts from

        The attribute stays a list, so `len(builder)` and appending a stage keep working after a clear
        """
        self.query = []


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

            self.query.append(self.add_fields_({
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
            }))
            self.query.append(self.sort_({SortPipeline.TEMP_KEY: sort_order, 'public_id': 1}))
            self.query.append(self.project_({SortPipeline.TEMP_KEY: 0}))
            return

        self.query.append(self.sort_(sort_key, sort_order))


    def __init_query(self, criteria: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Initialises the query with valid format

        Builds a fresh list and leaves `self.query` untouched; `build` and `count` assign the result

        Args:
            criteria (dict[str, Any] | list[dict[str, Any]]): Filter which should be applied

        Returns:
            list[dict[str, Any]]: The initialised query
        """
        query: list[dict[str, Any]] = []

        if isinstance(criteria, dict):
            query.append(self.match_(criteria))

        elif isinstance(criteria, list):
            for pipe in criteria:
                query.append(pipe)

        return query
