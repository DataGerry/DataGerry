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
Implementation of PipelineBuilder
"""
from logging import Logger, getLogger

from cmdb.manager.query_builder.builder import Builder
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                PipelineBuilder - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class PipelineBuilder(Builder):
    """
    A query builder for database aggregation pipelines

    This class helps in constructing and managing aggregation pipelines for 
    database queries, allowing for dynamic pipeline modifications

    Extends: Builder
    """

    def __init__(self, pipeline: list[dict] = None):
        """
        Initializes the PipelineBuilder

        Args:
            pipeline (list[dict], optional): A predefined pipeline to initialize with.
                                             Defaults to an empty list
        """
        self._pipeline = pipeline if pipeline is not None else []


    def __len__(self) -> int:
        """
        Returns the number of stages (pipes) in the pipeline

        Returns:
            int: The number of pipeline stages
        """
        return len(self.pipeline)


    def clear(self):
        """
        Clears the pipeline, removing all stages
        """
        self.pipeline = []


    @property
    def pipeline(self) -> list[dict]:
        """
        Retrieves the current aggregation pipeline

        Returns:
            list[dict]: The list of pipeline stages
        """
        return self._pipeline


    @pipeline.setter
    def pipeline(self, pipes: list[dict]):
        """
        Sets a new aggregation pipeline

        Args:
            pipes (list[dict]): A list of pipeline stages
        """
        self._pipeline = pipes


    def add_pipe(self, pipe: dict):
        """
        Adds a new stage to the pipeline

        Args:
            pipe (dict): The pipeline stage to add
        """
        self._pipeline.append(pipe)


    def build(self, *args, **kwargs) -> list[dict]:
        """
        Constructs and returns the aggregation pipeline

        Raises:
            NotImplementedError: This method should be implemented by subclasses

        Returns:
            list[dict]: The constructed pipeline (if implemented)
        """
        raise NotImplementedError("Subclasses must implement the build method.")
