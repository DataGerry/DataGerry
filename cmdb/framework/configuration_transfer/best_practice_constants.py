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

    <model_id>.json         an export of ``POST /export/configuration`` - unchanged but for its ``meta``
                            section, filled in by hand with what the assistant shows about it (``BestPracticeMetaKey``)

The model id is the file name without ``.json``: lower-case letters, digits and ``_`` only. A client names a model by
that id alone, never by a path

Several models can be applied together. Their entries are combined by name - the type's ``name``, the section
template's ``name``, the relation's ``relation_name``, the category's ``name``: one entry per name is created. Two
entries of one name must be identical in what the ``*_IGNORED_KEYS`` below leave to compare, or the combination is
refused; what they ignore is taken from the first model in card order
"""
import re
import sys

from cmdb.utils import BaseStrEnum
from cmdb.models.category_model.category_constants import CategoryKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

# The folder holding the models, next to this module (and bundled with the binary under the same relative path)
BEST_PRACTICE_MODELS_FOLDER: str = 'best_practice_models'

# The subfolder of the models folder the configured repository's models are synced into (hosted cloud only) - the one
# subfolder the catalogue reads; a model in it replaces a bundled model of the same id
REPOSITORY_MODELS_FOLDER: str = 'repository'

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
MODEL_REPLACED_BY_REPOSITORY: str = (
    "[best_practice_catalogue] The bundled best-practice model '%s' is replaced by the repository's model of that id"
)

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

# -------------------------------------------------------------------------------------------------------------------- #
#                                               COMBINING SEVERAL MODELS                                               #
# -------------------------------------------------------------------------------------------------------------------- #

# What two types of one name may differ in: identity and bookkeeping, the ACL (the import sets its own) and the
# description. Everything else - fields, sections, summary, SpecialType, ports, template claims - must be equal
TYPE_IGNORED_KEYS: frozenset[str] = frozenset({
    TypeSchemaKey.PUBLIC_ID.value,
    TypeSchemaKey.AUTHOR_ID.value,
    TypeSchemaKey.EDITOR_ID.value,
    TypeSchemaKey.CREATION_TIME.value,
    TypeSchemaKey.LAST_EDIT_TIME.value,
    TypeSchemaKey.VERSION.value,
    TypeSchemaKey.ACL.value,
    TypeSchemaKey.DESCRIPTION.value,
    TypeSchemaKey.ALIGNMENT_PENDING.value,
})

# What two types of one name may differ in inside ``render_meta``: the icon
TYPE_IGNORED_RENDER_META_KEYS: frozenset[str] = frozenset({TypeSchemaKey.ICON.value})

# What two section templates of one name may differ in
SECTION_TEMPLATE_IGNORED_KEYS: frozenset[str] = frozenset({SectionTemplateKey.PUBLIC_ID.value})

# What two relations of one name may differ in: identity, the description and how each side is drawn
RELATION_IGNORED_KEYS: frozenset[str] = frozenset({
    RelationKey.PUBLIC_ID.value,
    RelationKey.DESCRIPTION.value,
    RelationKey.RELATION_ICON_PARENT.value,
    RelationKey.RELATION_ICON_CHILD.value,
    RelationKey.RELATION_COLOR_PARENT.value,
    RelationKey.RELATION_COLOR_CHILD.value,
})

# What two categories of one name must agree on - their types are combined, their meta (icon, order) is the first's
CATEGORY_COMPARED_KEYS: tuple[str, ...] = (CategoryKey.LABEL.value, CategoryKey.PARENT.value)

# How a combination names the part of an entry that differs inside ``render_meta``
NESTED_PART: str = '{key}.{nested}'

# The ``information`` of a combined file: its name joins the models' titles, its description names the models
COMBINED_NAME_SEPARATOR: str = ' + '
COMBINED_DESCRIPTION: str = "Best-practice models combined by the start assistant: {model_ids}"


class CombinedEntryKind(BaseStrEnum):
    """What an entry is called in a combination's messages"""
    SECTION_TEMPLATE = 'section template'
    TYPE = 'type'
    CATEGORY = 'category'
    RELATION = 'relation'


# Why a combination of models is refused - answered to the client, all at once
ENTRY_DIFFERS: str = "The {kind} '{name}' differs between the models '{first}' and '{other}': {parts}"
TYPE_IN_TWO_CATEGORIES: str = (
    "The type '{name}' is in the category '{first_category}' in the model '{first}' and in the category "
    "'{other_category}' in the model '{other}' - a type can only be in one category"
)
MODEL_PROBLEM: str = "The model '{model_id}': {problem}"
