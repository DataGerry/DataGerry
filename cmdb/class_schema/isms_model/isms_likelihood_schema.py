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
Validation schema for IsmsLikelihood

An IsmsLikelihood is a likelihood level with a numeric calculation basis
(collection ``isms.likelihood``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsLikelihood.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_likelihood_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsLikelihood document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsLikelihood.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.isms_model.isms_likelihood_constants import LikelihoodKey

    return {
        LikelihoodKey.PUBLIC_ID.value: {  # public_id of the IsmsLikelihood
            'type': 'integer',
            'min': 1,
        },
        LikelihoodKey.NAME.value: {  # Name of the likelihood level
            'type': 'string',
            'required': True,
            'empty': False,
        },
        # Numeric weight of this likelihood level used in risk calculation. Greater than zero, as on
        # the impact scale - the other axis of the same matrix - and as the frontend's nonZeroValidator
        # requires: a zero-weight level would flatten every risk that uses it
        LikelihoodKey.CALCULATION_BASIS.value: {
            'type': 'float',
            'min': 1e-9,
            'required': True,
            'empty': False,
        },
        # Optional description of the likelihood level. Nullable because that is what the model emits
        # for a level created without one, and the frontend's edit form sends back what it was given -
        # a non-nullable rule here answered 'null value not allowed' on a save that changed nothing
        LikelihoodKey.DESCRIPTION.value: {
            'type': 'string',
            'required': False,
            'nullable': True,
        },
    }
