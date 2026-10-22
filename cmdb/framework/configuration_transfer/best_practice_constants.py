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
The names, file contract and messages of the best-practice data models the start assistant offers

A best-practice model is a pair of files in the ``best_practice_models`` folder next to this module:

    <model_id>.json         an export of ``GET /configuration_transfer/export``, unchanged
    <model_id>.meta.json    what the assistant shows about it (``BestPracticeMetaKey``)

The model id is the file name without ``.json``: lower-case letters, digits and ``_`` only. A client names a model by
that id alone, never by a path
"""
import re
import sys

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The folder holding the pairs, next to this module (and bundled with the binary under the same relative path)
BEST_PRACTICE_MODELS_FOLDER: str = 'best_practice_models'

# The two file name endings of a pair; a model file is every '.json' that is not a description file
MODEL_FILE_SUFFIX: str = '.json'
META_FILE_SUFFIX: str = '.meta.json'

# What a model id may be spelled as
MODEL_ID_PATTERN: re.Pattern[str] = re.compile(r'[a-z0-9_]+')

# The encoding both files are read in
MODEL_FILE_ENCODING: str = 'utf-8'

# Where a category without a stored order stands among the categories of a preview: after every ordered one
UNORDERED_CATEGORY_POSITION: int = sys.maxsize


class BestPracticeMetaKey(BaseStrEnum):
    """
    Keys of a model's description file

    TITLE, BADGE and SUMMARY are the model's card in the selection; DESCRIPTION, SUITED_FOR and PROFILES its details;
    CATEGORY_DESCRIPTIONS maps a category name of the model to the line shown above its types; ORDER sorts the cards
    (ties by model id)
    """
    TITLE = 'title'
    BADGE = 'badge'
    SUMMARY = 'summary'
    DESCRIPTION = 'description'
    SUITED_FOR = 'suited_for'
    PROFILES = 'profiles'
    CATEGORY_DESCRIPTIONS = 'category_descriptions'
    ORDER = 'order'


# Why a pair is left out of the catalogue - logged, never answered to a client
MODEL_ID_INVALID: str = "the model id '{model_id}' may only hold lower-case letters, digits and '_'"
META_FILE_MISSING: str = "its description file '{file_name}' is missing"
MODEL_FILE_MISSING: str = "the description file '{file_name}' has no model file"
FILE_UNREADABLE: str = "'{file_name}' could not be read as UTF-8 JSON: {detail}"
MODEL_FILE_PROBLEMS: str = "the model file is no transfer file: {problems}"
META_FILE_INVALID: str = "the description file is invalid: {errors}"
MODEL_LEFT_OUT: str = "[best_practice_catalogue] The best-practice model '%s' is left out: %s"

# What makes a model's file pair inconsistent - found by ``find_preview_problems``, failed by the catalogue test
UNKNOWN_DESCRIBED_CATEGORY: str = "the description file describes the category '{name}', which the model does not hold"
UNKNOWN_FIELD_TARGET: str = (
    "the field '{field}' of the type '{type}' targets the type ID {target}, which the model does not hold"
)
UNKNOWN_SECTION_TARGET: str = (
    "the section '{section}' of the type '{type}' references the type ID {target}, which the model does not hold"
)
UNKNOWN_RELATION_SIDE: str = "the relation '{relation}' names the type ID {target}, which the model does not hold"
UNKNOWN_CATEGORY_TYPE: str = "the category '{category}' holds the type ID {target}, which the model does not hold"
