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
The guard on the client-supplied ``?filter=`` aggregation pipeline

**What a list-shaped ``?filter=`` used to be.** ``BaseQueryBuilder.__init_query`` splices every element
of a list filter into the aggregation verbatim, and the ISMS report routes splice it into a pipeline of
their own. Neither checked what the stages were. Verified against this code on 2026-09-16, as an
ordinary authenticated caller:

* ``$lookup`` / ``$graphLookup`` / ``$unionWith`` read **any** collection in the database, and
  ``GET /users/?filter=[…{"$lookup":{"from":"management.users",…,"as":"email"}}]`` answered **200 with
  the stored password digest in the body** - bypassing ``to_public_json``, the method written to keep
  that digest out of every user response
* ``$function`` executes **server-side JavaScript**, and it does so from inside ``$match``/``$expr`` -
  the one stage any allow-list has to permit
* ``$out`` / ``$merge`` were refused only because the pager appends ``$sort`` / ``$skip`` after the
  client's stages and a write stage must be last. An ordering accident, not a guard

**Where the guard sits, and why not at the query builder.** The natural-looking place is
``__init_query``, the one funnel every list route's criteria passes through. It is the wrong place
twice over: the ISMS report routes consume ``params.filter`` directly and never reach it, and the
criteria that *does* reach it is not always the client's - ``objects_manager`` builds its own pipeline
with a ``framework.types`` ``$lookup`` and an ``$unwind`` and hands it over as criteria. A guard there
would miss the first and refuse the second. So it runs where the client's value **enters**:
``CollectionParameters.__init__``, before any route, helper or manager can read it

That placement also settles the error. A ``ValueError`` raised in the parameter constructor is turned
into an HTTP 400 by the ``parse_*_parameters`` decorators, carrying its own message - so a refused
stage is reported as a refused stage, rather than surfacing much later as the route's generic
*"Could not iterate the requested X!"*

**Why the allow-list is not tighter.** ``$lookup`` and ``$group`` are in it only because the Angular
frontend builds them into filters on live screens (object search, the reference tables, the
uncategorized-types view). Removing them needs server-side routes first, tracked as tier 2 **T204** and
**T205**; ``ALLOWED_LOOKUP_COLLECTIONS`` bounds the damage in the meantime. An allow-listed ``$lookup``
into ``framework.objects`` still returns documents the object ACL never filters - that residue is
**T206**
"""
from typing import Any

from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    ALLOWED_LOOKUP_COLLECTIONS,
    ALLOWED_PIPELINE_STAGES,
    DENIED_EXPRESSION_OPERATORS,
    LookupKey,
    WRITE_PIPELINE_STAGES,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOOKUP_STAGE: str = '$lookup'


def assert_no_denied_expressions(value: Any) -> None:
    """
    Walks a stage body and refuses the expression operators that execute JavaScript

    Recursive because these are **expressions**, not stages: ``$function`` is legal wherever an
    expression is, so it rides inside a permitted stage at any depth - ``$match`` -> ``$expr`` ->
    ``$function`` is a plain filtered read that runs arbitrary JavaScript in the database process. A
    guard that only inspected stage names would let every one of them through

    Args:
        value (Any): Any part of a client-supplied stage - a dict, a list, or a leaf

    Raises:
        ValueError: When a denied operator appears anywhere in the value; the
            ``parse_*_parameters`` decorator turns it into an HTTP 400
    """
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in DENIED_EXPRESSION_OPERATORS:
                raise ValueError(
                    f"The filter operator '{key}' is not permitted - it executes JavaScript in the database!"
                )

            assert_no_denied_expressions(nested)

    elif isinstance(value, list):
        for entry in value:
            assert_no_denied_expressions(entry)


def assert_lookup_is_allowed(lookup: Any) -> None:
    """
    Checks one ``$lookup`` body: its target collection, and anything it nests

    ``$lookup`` is the one permitted stage that reads a **different** collection, so its ``from`` is
    allow-listed; without that bound it reads the user collection and returns password digests. Its
    optional ``pipeline`` is a pipeline in its own right and gets the same treatment as the outer one -
    otherwise a nested stage would be an unguarded second entrance

    Args:
        lookup (Any): The body of a ``$lookup`` stage

    Raises:
        ValueError: When the body is not a document, targets a collection that is not allow-listed,
            or nests something the guard refuses
    """
    if not isinstance(lookup, dict):
        raise ValueError("A '$lookup' filter stage must be a document!")

    target: Any = lookup.get(LookupKey.FROM.value)

    if target not in ALLOWED_LOOKUP_COLLECTIONS:
        allowed: str = ', '.join(sorted(ALLOWED_LOOKUP_COLLECTIONS))

        raise ValueError(
            f"A '$lookup' filter stage may only target {allowed} (got {target!r})!"
        )

    nested_pipeline: Any = lookup.get(LookupKey.PIPELINE.value)

    if nested_pipeline is not None:
        assert_pipeline_stages_are_allowed(nested_pipeline)

    assert_no_denied_expressions(lookup.get(LookupKey.LET.value))


def assert_stage_is_allowed(stage: Any) -> None:
    """
    Checks a single aggregation stage against the allow-list

    Args:
        stage (Any): One element of a list-shaped ``?filter=``

    Raises:
        ValueError: When the stage is not a single-key document, names a write stage, or names an
            operator that is not allow-listed
    """
    if not isinstance(stage, dict) or len(stage) != 1:
        raise ValueError("Each entry of a list-shaped 'filter' must be a document naming one aggregation stage!")

    stage_name: str = next(iter(stage))

    if stage_name in WRITE_PIPELINE_STAGES:
        raise ValueError(f"The filter stage '{stage_name}' is not permitted - a filter may not write!")

    if stage_name not in ALLOWED_PIPELINE_STAGES:
        allowed: str = ', '.join(sorted(ALLOWED_PIPELINE_STAGES))

        raise ValueError(f"The filter stage '{stage_name}' is not permitted (allowed: {allowed})!")

    body: Any = stage[stage_name]

    if stage_name == LOOKUP_STAGE:
        assert_lookup_is_allowed(body)
    else:
        assert_no_denied_expressions(body)


def assert_pipeline_stages_are_allowed(stages: Any) -> None:
    """
    Checks a list-shaped filter, stage by stage

    Args:
        stages (Any): The list-shaped ``?filter=`` value, or a ``$lookup``'s nested pipeline

    Raises:
        ValueError: When the value is not a list, or any stage is refused
    """
    if not isinstance(stages, list):
        raise ValueError("A pipeline-shaped 'filter' must be a list of aggregation stages!")

    for stage in stages:
        assert_stage_is_allowed(stage)


def assert_client_filter_is_allowed(criteria: Any) -> None:
    """
    The entry point: checks a client-supplied ``?filter=`` in either of its two shapes

    A **dict** filter is wrapped in a single ``$match`` downstream, so it never introduces a stage -
    but it still carries expressions, and ``{"$where": …}`` or an ``$expr`` holding ``$function`` is
    exactly as dangerous there. A **list** filter is spliced in as stages and gets the full check.
    Anything else is left alone: ``CollectionParameters`` normalises a missing filter to ``{}`` and the
    consumers already handle the two documented shapes

    Args:
        criteria (Any): The parsed ``?filter=`` value, before any route or manager reads it

    Raises:
        ValueError: When the filter contains anything the guard refuses; the
            ``parse_*_parameters`` decorator turns it into an HTTP 400
    """
    if isinstance(criteria, list):
        assert_pipeline_stages_are_allowed(criteria)
    elif isinstance(criteria, dict):
        assert_no_denied_expressions(criteria)
