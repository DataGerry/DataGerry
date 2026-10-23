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

A best-practice model is one file in the ``best_practice_models`` folder next to this module:

    <model_id>.json         an export of ``POST /configuration_transfer/export`` - unchanged but for its ``meta``
                            section, filled in by hand with what the assistant shows about it (``BestPracticeMetaKey``)

The model id is the file name without ``.json``: lower-case letters, digits and ``_`` only. A client names a model by
that id alone, never by a path
"""
import re
import sys

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The folder holding the models, next to this module (and bundled with the binary under the same relative path)
BEST_PRACTICE_MODELS_FOLDER: str = 'best_practice_models'

# The file name ending of a model file - every '.json' directly in the folder is one
MODEL_FILE_SUFFIX: str = '.json'

# What a model id may be spelled as
MODEL_ID_PATTERN: re.Pattern[str] = re.compile(r'[a-z0-9_]+')

# The encoding a model file is read in
MODEL_FILE_ENCODING: str = 'utf-8'

# Where a category without a stored order stands among the categories of a preview: after every ordered one
UNORDERED_CATEGORY_POSITION: int = sys.maxsize


class BestPracticeMetaKey(BaseStrEnum):
    """
    Keys of a transfer file's ``meta`` section - what the assistant shows about a best-practice model

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


# Why a model is left out of the catalogue - logged, never answered to a client
MODEL_ID_INVALID: str = "the model id '{model_id}' may only hold lower-case letters, digits and '_'"
FILE_UNREADABLE: str = "'{file_name}' could not be read as UTF-8 JSON: {detail}"
MODEL_FILE_PROBLEMS: str = "the model file is no transfer file: {problems}"
META_NOT_FILLED_IN: str = "its meta section is not filled in completely: {errors}"
MODEL_LEFT_OUT: str = "[best_practice_catalogue] The best-practice model '%s' is left out: %s"

# What makes a model file inconsistent - found by ``find_preview_problems``, failed by the catalogue test
UNKNOWN_DESCRIBED_CATEGORY: str = "the meta section describes the category '{name}', which the model does not hold"
UNKNOWN_FIELD_TARGET: str = (
    "the field '{field}' of the type '{type}' targets the type ID {target}, which the model does not hold"
)
UNKNOWN_SECTION_TARGET: str = (
    "the section '{section}' of the type '{type}' references the type ID {target}, which the model does not hold"
)
UNKNOWN_RELATION_SIDE: str = "the relation '{relation}' names the type ID {target}, which the model does not hold"
UNKNOWN_CATEGORY_TYPE: str = "the category '{category}' holds the type ID {target}, which the model does not hold"
