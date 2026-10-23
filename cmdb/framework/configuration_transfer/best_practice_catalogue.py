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
The catalogue of best-practice data models the start assistant offers

Reads the model files of the ``best_practice_models`` folder (``best_practice_constants`` holds the contract): every
``<model_id>.json`` is an export of ``POST /configuration_transfer/export`` whose ``meta`` section says what the
assistant shows about it. A model is offered only when its file reads as UTF-8 JSON, is a transfer file (its envelope
- what a database's version or content decides is the import's to judge) and its ``meta`` section is filled in
completely (the strict schema - an export writes it empty). **A model that is not is left out and logged at ERROR**:
one broken bundle never breaks the assistant, and the catalogue test fails it in CI before it ships.

The folder only changes with a release, so the bundled catalogue is read once per process
(``get_best_practice_catalogue``)
"""
import json
from dataclasses import dataclass
from functools import cache
from logging import Logger, getLogger
from pathlib import Path
from typing import Any

from cerberus import Validator

from cmdb.database.json_codec import object_hook
from cmdb.errors.configuration_transfer import BestPracticeModelError
from cmdb.framework.configuration_transfer.best_practice_constants import (
    BEST_PRACTICE_MODELS_FOLDER,
    FILE_UNREADABLE,
    META_NOT_FILLED_IN,
    MODEL_FILE_ENCODING,
    MODEL_FILE_PROBLEMS,
    MODEL_FILE_SUFFIX,
    MODEL_ID_INVALID,
    MODEL_ID_PATTERN,
    MODEL_LEFT_OUT,
    BestPracticeMetaKey,
)
from cmdb.framework.configuration_transfer.best_practice_meta_schema import get_best_practice_meta_schema
from cmdb.framework.configuration_transfer.configuration_transfer_constants import TransferFileKey
from cmdb.framework.configuration_transfer.transfer_components import TRANSFER_COMPONENT_NAMES
from cmdb.framework.configuration_transfer.transfer_file import find_transfer_file_problems
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


@dataclass(frozen=True)
class BestPracticeMeta:
    """
    What the assistant shows about one model - its file's meta section, validated

    Attributes:
        title (str): The model's name
        badge (str): The label above the name on its card
        summary (str): The card's text
        description (str): The details' text
        suited_for (tuple[str, ...]): Who the model is meant for
        profiles (tuple[str, ...]): The building blocks it was assembled from, as chips
        category_descriptions (dict[str, str]): Category name -> the line shown above its types
        order (int): Its place among the cards
    """
    title: str
    badge: str
    summary: str
    description: str
    suited_for: tuple[str, ...]
    profiles: tuple[str, ...]
    category_descriptions: dict[str, str]
    order: int


@dataclass(frozen=True)
class BestPracticeModel:
    """
    One offered model: its id, its description and the transfer file it is applied from

    Attributes:
        model_id (str): The file name without ``.json`` - the id a client names it by
        meta (BestPracticeMeta): What the assistant shows about it
        document (dict[str, Any]): The decoded transfer file, dates as datetimes (as an uploaded file is decoded)
    """
    model_id: str
    meta: BestPracticeMeta
    document: dict[str, Any]


class BestPracticeCatalogue:
    """
    The offered models, in card order (``order``, then the model id)
    """

    def __init__(self, models: list[BestPracticeModel]) -> None:
        """
        Sorts the models into card order

        Args:
            models (list[BestPracticeModel]): The models that loaded
        """
        self._models: tuple[BestPracticeModel, ...] = tuple(
            sorted(models, key=lambda model: (model.meta.order, model.model_id))
        )


    @property
    def models(self) -> tuple[BestPracticeModel, ...]:
        """
        The offered models in card order

        Returns:
            tuple[BestPracticeModel, ...]: The models
        """
        return self._models


    def get(self, model_id: str) -> BestPracticeModel | None:
        """
        One offered model by its id

        Args:
            model_id (str): The id a client named

        Returns:
            BestPracticeModel | None: The model, or None when no offered model has that id
        """
        return next((model for model in self._models if model.model_id == model_id), None)


def default_models_folder() -> Path:
    """
    The bundled folder of model files, next to this module - from the source tree and from the binary alike

    Returns:
        Path: The folder
    """
    return Path(__file__).resolve().parent / BEST_PRACTICE_MODELS_FOLDER


def model_id_of(path: Path) -> str:
    """
    The model id a model file names

    Args:
        path (Path): A ``<model_id>.json`` file

    Returns:
        str: The file name without ``.json``
    """
    return path.name[:-len(MODEL_FILE_SUFFIX)]


def find_model_files(folder: Path) -> list[Path]:
    """
    The model files of a folder: every ``.json`` directly in it, by name

    Args:
        folder (Path): The folder to read; a missing folder holds none

    Returns:
        list[Path]: The model files
    """
    if not folder.is_dir():
        return []

    return sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.name.endswith(MODEL_FILE_SUFFIX)
    )


def read_json_file(path: Path) -> Any:
    """
    Reads a model file as UTF-8 JSON, ``{'$date': ...}`` values as datetimes - as an uploaded file is decoded

    Args:
        path (Path): The file

    Raises:
        BestPracticeModelError: When it cannot be read, is no UTF-8 or no JSON

    Returns:
        Any: The decoded document
    """
    try:
        return json.loads(path.read_text(encoding=MODEL_FILE_ENCODING), object_hook=object_hook)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise BestPracticeModelError(FILE_UNREADABLE.format(file_name=path.name, detail=err)) from err


def build_meta(data: Any) -> BestPracticeMeta:
    """
    Validates a model's ``meta`` section against the strict schema and builds what it says

    Args:
        data (Any): The section

    Raises:
        BestPracticeModelError: When it is not filled in completely - every error named

    Returns:
        BestPracticeMeta: The description
    """
    validator = Validator(get_best_practice_meta_schema())

    if not isinstance(data, dict) or not validator.validate(data):
        errors: Any = validator.errors if isinstance(data, dict) else type(data).__name__
        raise BestPracticeModelError(META_NOT_FILLED_IN.format(errors=errors))

    return BestPracticeMeta(
        title=data[BestPracticeMetaKey.TITLE.value],
        badge=data[BestPracticeMetaKey.BADGE.value],
        summary=data[BestPracticeMetaKey.SUMMARY.value],
        description=data[BestPracticeMetaKey.DESCRIPTION.value],
        suited_for=tuple(data[BestPracticeMetaKey.SUITED_FOR.value]),
        profiles=tuple(data[BestPracticeMetaKey.PROFILES.value]),
        category_descriptions=dict(data[BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value]),
        order=data[BestPracticeMetaKey.ORDER.value],
    )


def load_model(model_path: Path) -> BestPracticeModel:
    """
    Loads one model file: its id, the file as a transfer file, its ``meta`` section - judged in that order

    Args:
        model_path (Path): A ``<model_id>.json`` file

    Raises:
        BestPracticeModelError: When the id is misspelt, the file cannot be read, is no transfer file or its ``meta``
            section is not filled in completely

    Returns:
        BestPracticeModel: The model
    """
    model_id: str = model_id_of(model_path)

    if not MODEL_ID_PATTERN.fullmatch(model_id):
        raise BestPracticeModelError(MODEL_ID_INVALID.format(model_id=model_id))

    document: Any = read_json_file(model_path)
    problems: list[str] = find_transfer_file_problems(document, TRANSFER_COMPONENT_NAMES)

    if problems:
        raise BestPracticeModelError(MODEL_FILE_PROBLEMS.format(problems='; '.join(problems)))

    meta: BestPracticeMeta = build_meta(document[TransferFileKey.META.value])

    return BestPracticeModel(model_id=model_id, meta=meta, document=document)


def load_catalogue(folder: Path) -> BestPracticeCatalogue:
    """
    Loads every model file of a folder, leaving out - and logging at ERROR - each one that cannot be offered

    Args:
        folder (Path): The folder of model files

    Returns:
        BestPracticeCatalogue: The models that loaded
    """
    models: list[BestPracticeModel] = []

    for model_path in find_model_files(folder):
        try:
            models.append(load_model(model_path))
        except BestPracticeModelError as err:
            LOGGER.error(MODEL_LEFT_OUT, model_id_of(model_path), err)

    return BestPracticeCatalogue(models)


@cache
def get_best_practice_catalogue() -> BestPracticeCatalogue:
    """
    The bundled catalogue, read once per process

    Returns:
        BestPracticeCatalogue: The models of ``default_models_folder``
    """
    return load_catalogue(default_models_folder())
