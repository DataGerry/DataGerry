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

**What a list-shaped ``?filter=`` is.** ``BaseQueryBuilder.__init_query`` splices every element
of a list filter into the aggregation verbatim, and the ISMS report routes splice it into a pipeline of
their own. Neither checks what the stages are, which is what this guard is for, as an
ordinary authenticated caller:

* ``$lookup`` / ``$graphLookup`` / ``$unionWith`` read **any** collection in the database: unguarded,
  ``GET /users/?filter=[…{"$lookup":{"from":"management.users",…,"as":"email"}}]`` answers **200 with
  the stored password digest in the body** - bypassing ``to_public_json``, the method that keeps that
  digest out of every user response
* ``$function`` executes **server-side JavaScript**, and it does so from inside ``$match``/``$expr`` -
  the one stage any allow-list has to permit
* ``$out`` / ``$merge`` would fail unguarded only because the pager appends ``$sort`` / ``$skip`` after
  the client's stages and a write stage must be last. An ordering accident, not a guard
* an expression can be made to do **unbounded work inside one document**, and MongoDB checks a query's
  time budget (``maxTimeMS``) only between documents. ``$map`` nested five deep over a 50-entry array
  ran 104 s on three documents under the 10 s budget; ``$range``, a ``$reduce`` that reads its running
  value twice, or a chain of stages each doubling an array do the same through memory

**What the guard checks.** Stage names against ``ALLOWED_PIPELINE_STAGES``; a ``$lookup``'s target
against ``ALLOWED_LOOKUP_COLLECTIONS``; every operator below the stages against
``ALLOWED_FILTER_OPERATORS`` (the JavaScript ones with a message of their own); and, so that each
document costs work in proportion to its own size, four loop rules: no ``$map`` / ``$reduce`` inside
another one's ``in``, an ``in`` reads only its loop's variables, a ``$reduce`` reads its running value
once, an array join takes two operands. Last, the whole filter is held to ``MAX_FILTER_STAGES`` and
``MAX_ARRAY_BUILDING_OPERATORS``, which bounds how far it can grow an array

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

**Why the allow-lists are not tighter.** ``$lookup``, ``$group`` and the array operators are in them only
because the Angular frontend builds them into filters on live screens (object search, the reference
tables). Removing them needs server-side routes first; ``ALLOWED_LOOKUP_COLLECTIONS`` and the loop
rules bound the damage. An allow-listed ``$lookup`` into ``framework.objects`` still returns documents
the object ACL never filters
"""
from typing import Any

from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    ALLOWED_FILTER_OPERATORS,
    ALLOWED_LOOKUP_COLLECTIONS,
    ALLOWED_PIPELINE_STAGES,
    ARRAY_BUILDING_OPERATORS,
    ARRAY_COMBINING_OPERATORS,
    DEFAULT_MAP_VARIABLE,
    DENIED_EXPRESSION_OPERATORS,
    FIELD_PATH_SEPARATOR,
    ITERATING_EXPRESSION_OPERATORS,
    MAX_ARRAY_BUILDING_OPERATORS,
    MAX_ARRAY_OPERANDS,
    MAX_FILTER_STAGES,
    MAX_REDUCE_VALUE_READS,
    OPERATOR_PREFIX,
    REDUCE_OPERATOR,
    REDUCE_VALUE_VARIABLE,
    REDUCE_VARIABLES,
    VARIABLE_PREFIX,
    IterationKey,
    LookupKey,
    WRITE_PIPELINE_STAGES,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOOKUP_STAGE: str = '$lookup'


def assert_operator_is_allowed(operator: str) -> None:
    """
    Checks one operator key against the deny-list and then the allow-list

    The JavaScript operators are looked up first so their refusal says why; everything else outside
    ``ALLOWED_FILTER_OPERATORS`` is refused by absence, the way an unknown stage is

    Args:
        operator (str): A ``$``-prefixed key found below a filter's stages

    Raises:
        ValueError: When the operator executes JavaScript or is not allow-listed
    """
    if operator in DENIED_EXPRESSION_OPERATORS:
        raise ValueError(f"The filter operator '{operator}' is not permitted - it executes JavaScript in the database!")

    if operator not in ALLOWED_FILTER_OPERATORS:
        allowed: str = ', '.join(sorted(ALLOWED_FILTER_OPERATORS))

        raise ValueError(f"The filter operator '{operator}' is not permitted (allowed: {allowed})!")


def loop_variables_of(operator: str, body: dict[str, Any]) -> frozenset[str]:
    """
    The variables a ``$map`` / ``$reduce`` binds for its ``in``

    Args:
        operator (str): ``$map`` or ``$reduce``
        body (dict[str, Any]): The operator's body

    Returns:
        frozenset[str]: ``value`` and ``this`` for a ``$reduce``; the ``as`` name, or ``this``, for a ``$map``
    """
    if operator == REDUCE_OPERATOR:
        return REDUCE_VARIABLES

    return frozenset({body.get(IterationKey.AS.value, DEFAULT_MAP_VARIABLE)})


def variable_name(reference: str) -> str | None:
    """
    The variable a ``$$``-reference reads, without the path below it

    Args:
        reference (str): Any string from a filter

    Returns:
        str | None: ``this`` for ``$$this.value``; None when the string is not a variable reference
    """
    if not reference.startswith(VARIABLE_PREFIX):
        return None

    return reference[len(VARIABLE_PREFIX):].split(FIELD_PATH_SEPARATOR, 1)[0]


def assert_reads_only_loop_variables(reference: str, loop_variables: frozenset[str]) -> None:
    """
    Checks a string inside a loop's ``in``: a field path or a foreign variable there is refused

    ``in: '$fields'`` re-reads a whole stored array for every element, so a linear loop becomes a
    quadratic one; ``$$ROOT`` / ``$$CURRENT`` do the same with the whole document. A string that is
    not a reference (a format, a type name) is a literal and is left alone

    Args:
        reference (str): Any string found inside the ``in``
        loop_variables (frozenset[str]): The variables the enclosing loop binds

    Raises:
        ValueError: When the string reads a field path or a variable the loop does not bind
    """
    if not reference.startswith(OPERATOR_PREFIX) or variable_name(reference) in loop_variables:
        return

    raise ValueError(
        f"'{reference}' is not permitted inside the 'in' of a '$map' / '$reduce' - "
        f"it may only read the loop's own variables!"
    )


def count_value_reads(value: Any) -> int:
    """
    Counts the references to a ``$reduce``'s running value (``$$value`` or a path below it)

    Args:
        value (Any): A ``$reduce``'s ``in``, or any part of it

    Returns:
        int: How many strings in it read the running value
    """
    if isinstance(value, dict):
        return sum(count_value_reads(nested) for nested in value.values())

    if isinstance(value, list):
        return sum(count_value_reads(entry) for entry in value)

    if isinstance(value, str):
        return int(variable_name(value) == REDUCE_VALUE_VARIABLE)

    return 0


def assert_iteration_is_allowed(operator: str, body: Any, loop_variables: frozenset[str] | None) -> None:
    """
    Checks a ``$map`` / ``$reduce`` against the loop rules, then walks its parts

    Its ``input`` / ``initialValue`` are evaluated once and walked like any expression; its ``in`` runs
    once per element, so it is walked with the loop's variables as the only ones it may read

    Args:
        operator (str): ``$map`` or ``$reduce``
        body (Any): The operator's body
        loop_variables (frozenset[str] | None): The variables of an enclosing loop, None outside one

    Raises:
        ValueError: When the loop sits inside another loop's ``in``, its body is not a document, its
            ``in`` reads more than its own variables, or a ``$reduce`` reads its running value twice
    """
    if loop_variables is not None:
        raise ValueError(f"A '{operator}' is not permitted inside the 'in' of another '$map' / '$reduce'!")

    if not isinstance(body, dict):
        raise ValueError(f"A '{operator}' filter expression must be a document!")

    if operator == REDUCE_OPERATOR and count_value_reads(body.get(IterationKey.IN.value)) > MAX_REDUCE_VALUE_READS:
        raise ValueError("The 'in' of a '$reduce' may read '$$value' only once - reading it twice doubles it!")

    for key, part in body.items():
        if key == IterationKey.IN.value:
            assert_expressions_are_allowed(part, loop_variables_of(operator, body))
        else:
            assert_expressions_are_allowed(part)


def assert_array_operands_are_bounded(operator: str, operands: Any) -> None:
    """
    Checks that an array join takes a list of at most ``MAX_ARRAY_OPERANDS`` operands

    Args:
        operator (str): ``$concatArrays`` or ``$setUnion``
        operands (Any): The operator's value

    Raises:
        ValueError: When the value is not a list, or lists more operands than permitted
    """
    if not isinstance(operands, list) or len(operands) > MAX_ARRAY_OPERANDS:
        raise ValueError(f"A '{operator}' may join at most {MAX_ARRAY_OPERANDS} arrays, given as a list!")


def assert_expressions_are_allowed(value: Any, loop_variables: frozenset[str] | None = None) -> None:
    """
    Walks a stage body and checks every operator and loop in it

    Recursive because operators are **expressions**, not stages: ``$function`` is legal wherever an
    expression is, so it rides inside a permitted stage at any depth - ``$match`` -> ``$expr`` ->
    ``$function`` is a plain filtered read that runs arbitrary JavaScript in the database process. A
    guard that only inspected stage names would let every one of them through, and the same holds for
    the expressions that make one document arbitrarily expensive

    Args:
        value (Any): Any part of a client-supplied stage - a dict, a list, or a leaf
        loop_variables (frozenset[str] | None): The variables of the loop whose ``in`` this is, None
            outside one

    Raises:
        ValueError: When an operator is denied or not allow-listed, or a loop or array join breaks
            its rules; the ``parse_*_parameters`` decorator turns it into an HTTP 400
    """
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.startswith(OPERATOR_PREFIX):
                assert_operator_is_allowed(key)

                if key in ITERATING_EXPRESSION_OPERATORS:
                    assert_iteration_is_allowed(key, nested, loop_variables)
                    continue

                if key in ARRAY_COMBINING_OPERATORS:
                    assert_array_operands_are_bounded(key, nested)

            assert_expressions_are_allowed(nested, loop_variables)

    elif isinstance(value, list):
        for entry in value:
            assert_expressions_are_allowed(entry, loop_variables)

    elif isinstance(value, str) and loop_variables is not None:
        assert_reads_only_loop_variables(value, loop_variables)


def count_array_building_operators(value: Any) -> int:
    """
    Counts the ``$map`` / ``$reduce`` / ``$concatArrays`` / ``$setUnion`` in any part of a filter

    Args:
        value (Any): A filter, a stage, or any part of one

    Returns:
        int: How many array-building operators it holds, at any depth
    """
    if isinstance(value, dict):
        return sum(int(key in ARRAY_BUILDING_OPERATORS) + count_array_building_operators(nested)
                   for key, nested in value.items())

    if isinstance(value, list):
        return sum(count_array_building_operators(entry) for entry in value)

    return 0


def count_stages(stages: list[dict[str, Any]]) -> int:
    """
    Counts a pipeline's stages, those of its ``$lookup`` sub-pipelines included

    Args:
        stages (list[dict[str, Any]]): A pipeline the guard has already accepted stage by stage

    Returns:
        int: The number of stages, at every depth
    """
    total: int = len(stages)

    for stage in stages:
        lookup: Any = stage.get(LOOKUP_STAGE)

        if isinstance(lookup, dict) and isinstance(lookup.get(LookupKey.PIPELINE.value), list):
            total += count_stages(lookup[LookupKey.PIPELINE.value])

    return total


def assert_filter_size_is_bounded(criteria: list[dict[str, Any]] | dict[str, Any]) -> None:
    """
    Holds a whole filter to ``MAX_FILTER_STAGES`` and ``MAX_ARRAY_BUILDING_OPERATORS``

    The loop rules bound what one expression does with one array; these bound how often a filter can
    do it. Each array join at most doubles an array, so the operator cap is a cap on growth

    Args:
        criteria (list[dict[str, Any]] | dict[str, Any]): A filter the guard has already accepted

    Raises:
        ValueError: When the filter holds more stages or array-building operators than permitted
    """
    if isinstance(criteria, list) and count_stages(criteria) > MAX_FILTER_STAGES:
        raise ValueError(f"A filter may hold at most {MAX_FILTER_STAGES} stages, nested pipelines included!")

    if count_array_building_operators(criteria) > MAX_ARRAY_BUILDING_OPERATORS:
        raise ValueError(
            f"A filter may hold at most {MAX_ARRAY_BUILDING_OPERATORS} '$map' / '$reduce' / '$concatArrays' / "
            f"'$setUnion' operators!"
        )


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

    assert_expressions_are_allowed(lookup.get(LookupKey.LET.value))


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
        assert_expressions_are_allowed(body)


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
        assert_expressions_are_allowed(criteria)
    else:
        return

    assert_filter_size_is_bounded(criteria)
