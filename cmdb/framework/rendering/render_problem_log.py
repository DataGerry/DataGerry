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
Implementation of RenderProblemLog

A render that cannot build one piece of its answer leaves that piece out and carries on. This module is
what makes such a render tell-apart from a complete one: every loss is recorded against the object whose
render it cost - which `CmdbMultiRender` copies onto `RenderResult.render_problems` - and logged once
per render, however many objects run into it
"""
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from logging import ERROR, WARNING, Logger
from typing import Any

from cmdb.framework.rendering.render_constants import RenderProblemCode, RenderProblemKey
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                               RenderProblemLog - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class RenderProblemLog:
    """
    Records what each object's render lost, and logs every kind of loss once

    Recording and logging are kept apart on purpose. The record is per OBJECT: each object of a list
    render that lost a piece says so on its own result. The log is per RENDER: one broken type
    definition walked by a hundred objects is one log line, not a hundred

    Attributes:
        logger (Logger): Where the problems are logged
        reported (set[tuple[Any, ...]]): The dedup keys of the problems already logged. A nested render
            is handed its outer render's set, so it does not log them again
        problems_by_object (dict[int, list[dict[str, Any]]]): The recorded problems, keyed by the
            public_id of the object whose render they cost
        current_object_id (int | None): The object being rendered right now, where a problem is recorded
            when no object is named
    """

    def __init__(self, logger: Logger, reported: set[tuple[Any, ...]] | None = None) -> None:
        """
        Initialises an empty RenderProblemLog

        Args:
            logger (Logger): Where the problems are logged - the renderer's own logger, so a log line
                keeps naming the module that lost the data
            reported (set[tuple[Any, ...]] | None): An outer render's set of logged problems to share.
                Defaults to None, which starts a fresh one
        """
        self.logger: Logger = logger
        self.reported: set[tuple[Any, ...]] = reported if reported is not None else set()
        self.problems_by_object: dict[int, list[dict[str, Any]]] = {}
        self.current_object_id: int | None = None


    @contextmanager
    def rendering(self, object_id: int) -> Iterator[None]:
        """
        Marks an object as the one being rendered for the duration of the block

        Args:
            object_id (int): The public_id of the object being rendered

        Yields:
            None: Control, with the object marked; the mark is cleared however the block ends
        """
        self.current_object_id = object_id

        try:
            yield
        finally:
            self.current_object_id = None


    def report(
        self,
        code: RenderProblemCode,
        message: str,
        *message_args: Any,
        section: str | None = None,
        field: str | None = None,
        external_link: str | None = None,
        object_ids: Iterable[int] | None = None,
        log_key: tuple[Any, ...] = (),
        log_level: int = WARNING,
    ) -> None:
        """
        Records that a render answered less than the stored data holds, and logs it once

        * **Records** a ``RenderProblemKey`` entry for every object named by ``object_ids`` - by
          default the object being rendered. The entry says WHERE the loss is, never the exception's
          text, which can carry internals a client has no business reading; that stays in the log
        * **Logs** the message, unless a problem with the same dedup key was already logged. The key
          is the code, the section, the field and the link, plus ``log_key`` for whatever else tells
          two problems of that code apart (the type, the referenced object, ...). An ERROR carries the
          traceback: it is kept for failures of the database or the code, where the stack is the lead

        With no object being rendered and no object ids given - a reference answered on its own, say -
        the problem is only logged. An empty ``object_ids`` does the same on purpose, for a problem that
        costs the render nothing visible

        Args:
            code (RenderProblemCode): What was lost
            message (str): A %-style log message
            *message_args (Any): Arguments for the log message
            section (str | None): The type section the problem belongs to. Defaults to None
            field (str | None): The field the problem belongs to. Defaults to None
            external_link (str | None): The external link the problem belongs to. Defaults to None
            object_ids (Iterable[int] | None): The objects to record it for. Defaults to the object
                being rendered
            log_key (tuple[Any, ...]): What else tells two problems of this code apart. Defaults to ()
            log_level (int): The level to log at. Defaults to WARNING
        """
        problem: dict[str, Any] = {
            RenderProblemKey.CODE.value: code.value,
            RenderProblemKey.SECTION.value: section,
            RenderProblemKey.FIELD.value: field,
            RenderProblemKey.EXTERNAL_LINK.value: external_link,
        }

        if object_ids is None:
            object_ids = () if self.current_object_id is None else (self.current_object_id,)

        for object_id in object_ids:
            self.record([problem], object_id)

        dedup_key: tuple[Any, ...] = (code, section, field, external_link, *log_key)

        if dedup_key in self.reported:
            return

        self.reported.add(dedup_key)

        self.logger.log(log_level, message, *message_args, exc_info=log_level >= ERROR)


    def record(self, problems: Iterable[dict[str, Any]], object_id: int | None = None) -> None:
        """
        Adds problems to an object's record, each entry at most once

        Used directly to hand a nested render's problems up to the object it was rendered for: what the
        nested render lost is missing from that object's reference section

        Args:
            problems (Iterable[dict[str, Any]]): The ``RenderProblemKey`` entries to add
            object_id (int | None): The object they belong to. Defaults to the object being rendered;
                nothing is recorded when no object is being rendered
        """
        if object_id is None:
            object_id = self.current_object_id

        if object_id is None:
            return

        recorded: list[dict[str, Any]] = self.problems_by_object.setdefault(object_id, [])

        for problem in problems:
            if problem not in recorded:
                recorded.append(dict(problem))


    def problems_for(self, object_id: int) -> list[dict[str, Any]]:
        """
        Answers a copy of the problems recorded for an object

        Args:
            object_id (int): The public_id of the object

        Returns:
            list[dict[str, Any]]: The recorded entries, empty when the object's render lost nothing
        """
        return [dict(problem) for problem in self.problems_by_object.get(object_id, [])]
