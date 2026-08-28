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
Implementation of CollectionParameters - the pager of every list route

The values are validated HERE rather than left to MongoDB. They used not to be, and every bad pager
value therefore failed inside the aggregation and was reported by the route's
``except …IterationError`` arm: ``?page=0`` answered *"Failed to retrieve Objects from the database!"*,
blaming the database for a client's page number. A rejection raised from this module becomes an HTTP 400
instead, because the ``parse_*_parameters`` decorators abort 400 on anything raised out of ``from_data``

Two rules behind the validation:

* **A page below 1 is clamped, not refused.** A caller asking for page 0 is asking for the start of the
  collection, and the frontend does send ``page: 0`` in one place. It previously produced a negative
  ``$skip`` and a 400.
* **A limit or order that has no meaning is refused.** ``limit`` may be ``0`` (unlimited) or positive;
  a negative page size is nonsense and used to be accepted and echoed back to the frontend. ``order``
  may only be ``1`` or ``-1``, the two values ``$sort`` accepts

Naming: what the query string calls ``filter`` is called ``criteria`` from the constructor inward, which
is what ``get_builder_params`` already handed to ``BuilderParameters``. The wire keys are unchanged in
both directions - ``?filter=`` on the way in and ``filter`` in the echoed ``parameters`` block - because
they are frontend contract; only the constructor parameter is renamed, which also stops it shadowing the
``filter`` builtin. The mapping happens in the constructor rather than in a ``from_data`` override, so
the JSON parsing of ``filter`` can stay in ``APIParameters.from_data``, which has to see the value under
its wire name. The attribute stays ``self.filter``: it is read and mutated at ~28 call sites across six
modules, so renaming that too is recorded as a separate decision rather than folded in here
"""
from typing import Any

from cmdb.interface.rest_api.responses.response_parameters.api_parameters import APIParameters
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    BuilderParamKey,
    DEFAULT_LIMIT,
    DEFAULT_SORT,
    FIRST_PAGE,
    ParameterKey,
    SORT_ASCENDING,
    UNLIMITED_LIMIT,
    VALID_SORT_ORDERS,
)
# -------------------------------------------------------------------------------------------------------------------- #


def _coerce_limit(limit: Any) -> int:
    """
    Coerces the ``limit`` query value to an int, refusing a negative page size

    ``0`` is kept as-is: it means "no limit" and the frontend relies on it

    Args:
        limit (Any): The raw ``limit`` value, a string when it came from the query parser

    Raises:
        ValueError: When the value is not an integer or is negative; the ``parse_*_parameters``
            decorator turns that into an HTTP 400

    Returns:
        int: The page size to apply
    """
    if limit is None or limit == '':
        return DEFAULT_LIMIT

    coerced = int(limit)

    if coerced < UNLIMITED_LIMIT:
        raise ValueError(f"The 'limit' parameter must not be negative (got {coerced})!")

    return coerced


def _coerce_order(order: Any) -> int:
    """
    Coerces the ``order`` query value to an int, refusing anything but ascending / descending

    Args:
        order (Any): The raw ``order`` value, a string when it came from the query parser

    Raises:
        ValueError: When the value is not an integer or is not 1 / -1

    Returns:
        int: The sort direction to apply
    """
    if order is None or order == '':
        return SORT_ASCENDING

    coerced = int(order)

    if coerced not in VALID_SORT_ORDERS:
        raise ValueError(f"The 'order' parameter must be 1 (ascending) or -1 (descending), got {coerced}!")

    return coerced


def _coerce_page(page: Any) -> int:
    """
    Coerces the ``page`` query value to an int, clamping anything below the first page

    A caller asking for page 0 or a negative page is asking for the start of the collection, so the
    value is clamped rather than refused - it used to produce a negative ``$skip``

    Args:
        page (Any): The raw ``page`` value, a string when it came from the query parser

    Raises:
        ValueError: When the value is not an integer at all

    Returns:
        int: The page number to apply, never below FIRST_PAGE
    """
    if page is None or page == '':
        return FIRST_PAGE

    return max(int(page), FIRST_PAGE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             CollectionParameters - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class CollectionParameters(APIParameters):
    """
    Rest API class for parameters passed by a http request on a collection route
    """

    def __init__(
        self,
        query_string: str = None,
        limit: int = None,
        sort: str = DEFAULT_SORT,
        order: int = SORT_ASCENDING,
        page: int = None,
        criteria: list[dict] | dict = None,
        **kwargs: Any
    ) -> None:
        """
        Constructor of the CollectionParameters

        Every value may arrive as a string from the query parser, so each is coerced and validated
        here; see the module docstring for why a bad value has to be rejected at this layer

        Args:
            query_string (str | None): The raw http query string. Can be used when the parsed
                parameters are not enough
            limit (int | None): The max number of resources returned (pageSize). 0 means unlimited.
                Defaults to DEFAULT_LIMIT
            sort (str): The query element used as the sort id (nested resources are possible via a dot)
            order (int): The sort direction, 1 (ascending) or -1 (descending)
            page (int | None): The current page; (limit * (page - 1)) elements are skipped. Clamped to
                FIRST_PAGE
            criteria (list[dict] | dict | None): A generic query filter based on
                https://docs.mongodb.com/compass/master/query/filter/ - the query string calls this
                ``filter``, which is the name it keeps on the wire and on the attribute
            **kwargs (Any): Additional optional parameters, forwarded to APIParameters. The wire key
                ``filter`` arrives here and is mapped onto ``criteria``, which is why this class needs
                no ``from_data`` of its own - the JSON parsing stays in APIParameters.from_data, which
                must see the value under its wire name

        Raises:
            ValueError: When limit / order / page cannot be coerced, when limit is negative or when
                order is not 1 / -1
        """
        # The query string calls it 'filter'; everything from here inward calls it criteria
        criteria = kwargs.pop(ParameterKey.FILTER.value, criteria)

        self.limit: int = _coerce_limit(limit)
        self.sort: str = sort or DEFAULT_SORT
        self.order: int = _coerce_order(order)
        self.page: int = _coerce_page(page)

        if self.limit == UNLIMITED_LIMIT:
            self.skip: int = 0
        else:
            self.skip = (self.page - FIRST_PAGE) * self.limit

        self.filter: list[dict] | dict = criteria or {}

        super().__init__(query_string=query_string, **kwargs)


    @staticmethod
    def to_dict(parameters: "CollectionParameters") -> dict[str, Any]:
        """
        Converts the parameters into the ``parameters`` block of a GetMultiResponse

        The keys are frontend contract - the Angular list services read this block back - so the
        criteria is echoed under its wire name ``filter``

        Args:
            parameters (CollectionParameters): The instance to convert

        Returns:
            dict[str, Any]: The pager as a dict, with ``projection`` present only when one was given
        """
        params: dict[str, Any] = {
            ParameterKey.LIMIT.value: parameters.limit,
            ParameterKey.SORT.value: parameters.sort,
            ParameterKey.ORDER.value: parameters.order,
            ParameterKey.PAGE.value: parameters.page,
            ParameterKey.FILTER.value: parameters.filter,
            ParameterKey.OPTIONAL.value: parameters.optional,
        }

        if parameters.projection:
            params[ParameterKey.PROJECTION.value] = parameters.projection

        return params


    @staticmethod
    def get_builder_params(params: "CollectionParameters") -> dict[str, Any]:
        """
        Extracts the attributes required for BuilderParameters

        Internal hand-off, not part of the frontend contract: the keys match the
        ``BuilderParameters`` constructor, which is where the wire's ``filter`` becomes ``criteria``

        Args:
            params (CollectionParameters): The pager to read

        Returns:
            dict[str, Any]: Keyword arguments for ``BuilderParameters``
        """
        return {
            BuilderParamKey.CRITERIA.value: params.filter,
            BuilderParamKey.LIMIT.value: params.limit,
            BuilderParamKey.SORT.value: params.sort,
            BuilderParamKey.ORDER.value: params.order,
            BuilderParamKey.SKIP.value: params.skip,
        }

    def __repr__(self) -> str:
        return f"""
                Parameters: Query({self.query_string}),
                Filter({self.filter}),
                Projection({self.projection}),
                Optional({self.optional})
                """
