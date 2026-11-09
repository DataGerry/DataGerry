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
The type ACL inside a client-supplied ``$lookup`` into the objects

**Why a join needs its own ACL.** The type ACL of a list route is a ``$match`` on the **outer** document's
``type_id``. A client ``$lookup`` into ``framework.objects`` pulls whole object documents into an array of
an outer document that has already passed, so the exclusion never sees them - and the client's own
``$match`` after the join can test their values: the total (or whether any row comes back) answers "does a
hidden object's field match my guess?", which reads any value of any hidden object one guess at a time.
Dropping the array from the response does not help, because the test runs inside the database.

**What this module does.** ``scope_object_lookups`` puts the type exclusion at the start of every
``$lookup``'s sub-pipeline that targets ``framework.objects`` - at any depth, since a ``$lookup``'s own
pipeline may join again. For the ``localField`` / ``foreignField`` form the exclusion goes into a
``pipeline`` next to the two fields, which MongoDB 5.0+ runs as an additional filter on the joined
documents. A join then sees exactly the objects the caller may read - the rule ``?search=`` already follows
- and nothing else about the query changes. A join into any other collection is left as it is: the client
pipeline guard refuses every other target, so only server-built criteria carry one.

**Where it runs.** On the client's filter as it enters, once the request user is known
(``scope_client_filter_lookups`` from the parameter decorators of ``APIBlueprint``) - the one place every
``?filter=`` passes through, including the routes that read the filter without the type ACL at all (the
ISMS reports and every list that iterates without a user). It costs one projected read of the denied types,
and only for a filter that joins the objects.

The caller's own value is never modified: a new criteria is built, so the ``filter`` echoed in a list
response stays what the client sent and does not reveal the denied type ids
"""
from typing import Any

from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    LookupKey,
    OBJECTS_LOOKUP_TARGET,
)
from cmdb.security.acl.builder import build_denied_types_condition, resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import Builder
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'filter_joins_objects',
    'scope_client_filter_lookups',
    'scope_object_lookups',
]

#: The stage key of a join, as a client filter spells it
LOOKUP_STAGE: str = '$lookup'

#: Raised when a filter joins the objects but no request user is known to scope the join for
UNSCOPED_OBJECT_JOIN_MESSAGE: str = (
    "A '$lookup' into the objects can only be run for a known user - the join is narrowed to the types they may read!"
)


def filter_joins_objects(criteria: Any) -> bool:
    """
    Whether a client filter contains a ``$lookup`` into ``framework.objects``, at any depth

    Args:
        criteria (Any): The parsed ``?filter=`` - a filter document or a list of stages

    Returns:
        bool: True when at least one join targets the objects
    """
    if not isinstance(criteria, list):
        return False

    return any(_stage_joins_objects(stage) for stage in criteria)


def _stage_joins_objects(stage: Any) -> bool:
    """
    Whether one stage is, or nests, a ``$lookup`` into ``framework.objects``

    Args:
        stage (Any): One element of a list-shaped filter

    Returns:
        bool: True when the stage joins the objects itself or inside its own pipeline
    """
    lookup: Any = stage.get(LOOKUP_STAGE) if isinstance(stage, dict) else None

    if not isinstance(lookup, dict):
        return False

    return lookup.get(LookupKey.FROM.value) == OBJECTS_LOOKUP_TARGET or filter_joins_objects(
        lookup.get(LookupKey.PIPELINE.value)
    )


def scope_object_lookups(criteria: Any, denied_type_ids: list[int]) -> Any:
    """
    Narrows every ``$lookup`` into ``framework.objects`` to the types the caller may read

    Answers a NEW criteria and leaves the given one untouched. Nothing changes when nothing is denied or the
    filter is a filter document (which cannot hold a stage)

    Args:
        criteria (Any): The parsed ``?filter=`` - a filter document or a list of stages
        denied_type_ids (list[int]): The CmdbTypes the caller may not read

    Returns:
        Any: The criteria with each object join opening on the type exclusion
    """
    if not denied_type_ids or not isinstance(criteria, list):
        return criteria

    return [_scope_stage(stage, denied_type_ids) for stage in criteria]


def _scope_stage(stage: Any, denied_type_ids: list[int]) -> Any:
    """
    Scopes one stage: a ``$lookup`` is rebuilt, every other stage is returned as it is

    Args:
        stage (Any): One element of a list-shaped filter
        denied_type_ids (list[int]): The CmdbTypes the caller may not read

    Returns:
        Any: The stage, with its join narrowed when it is one
    """
    lookup: Any = stage.get(LOOKUP_STAGE) if isinstance(stage, dict) else None

    if not isinstance(lookup, dict):
        return stage

    return {LOOKUP_STAGE: _scope_lookup(lookup, denied_type_ids)}


def _scope_lookup(lookup: dict[str, Any], denied_type_ids: list[int]) -> dict[str, Any]:
    """
    Rebuilds one ``$lookup`` body: its own pipeline scoped recursively, and opened by the type exclusion
    when it joins the objects

    A join into the objects without a pipeline (the ``localField`` / ``foreignField`` form) gets one holding
    only the exclusion

    Args:
        lookup (dict[str, Any]): The body of a ``$lookup`` stage
        denied_type_ids (list[int]): The CmdbTypes the caller may not read

    Returns:
        dict[str, Any]: A new body; the given one is not modified
    """
    nested: Any = lookup.get(LookupKey.PIPELINE.value)
    scoped_nested: list[Any] = scope_object_lookups(nested, denied_type_ids) if isinstance(nested, list) else []

    if lookup.get(LookupKey.FROM.value) == OBJECTS_LOOKUP_TARGET:
        scoped_nested = [Builder.match_(build_denied_types_condition(denied_type_ids)), *scoped_nested]

    if not scoped_nested and LookupKey.PIPELINE.value not in lookup:
        return dict(lookup)

    return {**lookup, LookupKey.PIPELINE.value: scoped_nested}


def scope_client_filter_lookups(criteria: Any, request_user: Any) -> Any:
    """
    Narrows a client filter's object joins to the types the request user may READ

    Resolves the denied types only when the filter joins the objects, so an ordinary filter costs nothing

    Args:
        criteria (Any): The parsed, guard-checked ``?filter=``
        request_user (Any): The CmdbUser the request is made for, or None when the route knows none

    Raises:
        ValueError: When the filter joins the objects and no request user is known

    Returns:
        Any: The criteria to run - the given one when there is nothing to scope
    """
    if not filter_joins_objects(criteria):
        return criteria

    if request_user is None:
        raise ValueError(UNSCOPED_OBJECT_JOIN_MESSAGE)

    return scope_object_lookups(criteria, resolve_denied_type_ids(request_user, AccessControlPermission.READ))
