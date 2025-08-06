# DATAGERRY - OpenSource Enterprise CMDB
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
Implementation of CollectionParameters
"""
import logging
from json import loads

from cmdb.interface.rest_api.responses.response_parameters.api_parameters import APIParameters
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             CollectionParameters - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class CollectionParameters(APIParameters):
    """
    Rest API class for parameters passed by a http request on a collection route
    """
    #TODO: REFACTOR-FIX (replace filter with criteria)
    def __init__(self, query_string: str = None, limit: int = None, sort: str = None,
                 order: int = None, page: int = None, filter: list[dict] | dict = None, **kwargs):
        """
        Constructor of the CollectionParameters.

        Args:
            query_string: The raw http query string. Can be used when the parsed parameters are not enough.
            limit: The max number of resources returned (pageSize).
            sort: The query element which is used as the sort id (nested resources are possible via (.) dot).
            order: The order sequence in which `way` the sort should be returned.
            page: The current page. N number of elements will be skip based on (limit * page)
            filter: A generic query filter based on https://docs.mongodb.com/compass/master/query/filter/
            **kwargs:
        """
        self.limit: int = int(limit or 10)
        self.sort: str = sort or 'public_id'
        self.order: int = int(order or 1)
        self.page: int = int((page or 1) or page < 1)

        if self.limit == 0:
            self.skip = 0
        else:
            self.skip: int = (self.page - 1) * self.limit

        self.filter: list[dict] | dict = filter or {}

        super().__init__(query_string=query_string, **kwargs)


    @classmethod
    def from_data(cls, query_string: str, **optional) -> "CollectionParameters":
        """
        Create a collection parameter instance from a http query string

        Args:
            query_string: raw query string
            **optional: list of optional http parameters

        Returns:
            CollectionParameters instance
        """
        if 'filter' in optional:
            optional['filter'] = loads(optional['filter'])
        if 'projection' in optional:
            optional['projection'] = loads(optional['projection'])

        return cls(query_string, **optional)


    @classmethod
    def to_dict(cls, parameters: "CollectionParameters") -> dict:
        """
        Get the object as a dict
        """
        params: dict = {
            'limit': parameters.limit,
            'sort': parameters.sort,
            'order': parameters.order,
            'page': parameters.page,
            'filter': parameters.filter,
            'optional': parameters.optional,
        }
        if parameters.projection:
            params.update({'projection': parameters.projection})
        return params


    @classmethod
    def get_builder_params(cls, params: "CollectionParameters") -> dict:
        """Extracts the attributes required for BuilderParameters"""
        return {
            'criteria': params.filter,
            'limit': params.limit,
            'sort': params.sort,
            'order': params.order,
            'skip': params.skip,
        }

    def __repr__(self) -> str:
        return f"""
                Parameters: Query({self.query_string}),
                Filter({self.filter}),
                Projection({self.projection}),
                Optional({self.optional})
                """
