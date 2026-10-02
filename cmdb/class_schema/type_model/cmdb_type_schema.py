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
Validation schema for CmdbType

A CmdbType defines the fields and sections from which its CmdbObjects are built
(collection ``framework.types``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbType.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_VERSION = '1.0.0'

# -------------------------------------------------------------------------------------------------------------------- #

def get_type_acl_schema() -> dict[str, Any]:
    """
    Builds the Cerberus rule for a CmdbType's ``acl`` block

    The one declaration of the block's shape, used by ``CmdbType.SCHEMA`` and by the type import, so a route write
    and an imported type are held to the same rule:

    * ``activated`` is a boolean - the listing query and the single read both decide on it, and only a real
      boolean means the same thing to both
    * ``groups.includes`` maps a CmdbUserGroup public_id (as a string key) to a list of AccessControlPermission
      values; an empty list is a group granted nothing

    Every part is optional and ``groups`` / ``includes`` may be null: the create route completes a partial block
    (``types_helper.normalize_type_acl``) and the model reads a null section as "no groups". An unknown key inside
    the block is purged by the route validator, as the model would drop it

    Returns:
        dict[str, Any]: The rule for the ``acl`` key
    """
    # Imported inside the builder, like the model constants below (see the class_schema convention)
    # pylint: disable=import-outside-toplevel
    from cmdb.security.acl.acl_constants import ACL_GROUP_KEY_PATTERN, AclKey
    from cmdb.security.acl.permission import AccessControlPermission

    permissions: list[str] = [permission.value for permission in AccessControlPermission]

    return {
        'type': 'dict',
        'required': False,
        'schema': {
            AclKey.ACTIVATED.value: {
                'type': 'boolean',
                'required': False,
            },
            AclKey.GROUPS.value: {
                'type': 'dict',
                'required': False,
                'nullable': True,
                'schema': {
                    AclKey.INCLUDES.value: {
                        'type': 'dict',
                        'required': False,
                        'nullable': True,
                        'keysrules': {
                            'type': 'string',
                            'regex': ACL_GROUP_KEY_PATTERN,
                        },
                        'valuesrules': {
                            'type': 'list',
                            'schema': {
                                'type': 'string',
                                'allowed': permissions,
                            },
                        },
                    },
                },
            },
        },
    }

# pylint: disable=R0801
def get_cmdb_type_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbType document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbType.SCHEMA
    """
    # Imported inside the builder: the model layer imports this module, so a module-level import
    # would close the cycle (see the class_schema convention)
    # pylint: disable=import-outside-toplevel
    from cmdb.models.type_model.section_type_enum import SectionType
    from cmdb.models.type_model.type_constants import NESTED_SUMMARY_PREFIX_DEFAULT

    return {
        'public_id': {  # public_id of the CmdbType
            'type': 'integer'
        },
        'name': {  # Unique name of the CmdbType
            'type': 'string',
            'required': True,
            'regex': r'(\w+)-*(\w)([\w-]*)'  # kebab case validation,
        },
        'label': {  # Label of the CmdbType (visible by users)
            'type': 'string',
            'required': False
        },
        'author_id': {  # public_id of the CmdbUser who created this CmdbType
            'type': 'integer',
            'required': True
        },
        'editor_id': {  # public_id of the CmdbUser who last edited this CmdbType
            'type': 'integer',
            'nullable': True,
            'required': False
        },
        'creation_time': {  # The datetime when this CmdbType was created
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'last_edit_time': {  # The datetime when the last editing of this CmdbType occured
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'selectable_as_parent': {  # If True, this location is selectable as a parent location for other locations
            'type': 'boolean',
            'default': True
        },
        'uses_ports': {  # If True, CmdbObjects of this CmdbType may carry physical ports (Port Connectivity)
            'type': 'boolean',
            'default': False
        },
        # Position of the ports section among this CmdbType's sections (0 = first). Only meaningful
        # while 'uses_ports' is True - the write paths force it back to 0 when the flag is off
        'port_section_index': {
            'type': 'integer',
            'required': False,
            'min': 0,
            'default': 0
        },
        'global_template_ids': {  # The names of the global CmdbSectionTemplates used by this CmdbType
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'string',
            }
        },
        'active': {  # If True, this CmdbType is active
            'type': 'boolean',
            'required': False,
            'default': True
        },
        'special_type': {  # The assigned SpecialType if any
            'type': 'string',
            'required': False,
            'nullable': True,
        },
        'fields': {
            'type': 'list',
            'required': False,
            'default': None,
            'schema': {
                'type': 'dict',
                'schema': {
                    "type": {
                        'type': 'string',  # Text, Password, Textarea, radio, select, date
                        'required': True
                    },
                    "required": {
                        'type': 'boolean',
                        'required': False
                    },
                    "name": {
                        'type': 'string',
                        'required': True
                    },
                    "rows": {
                        'type': 'integer',
                        'required': False
                    },
                    "label": {
                        'type': 'string',
                        'required': True
                    },
                    "description": {
                        'type': 'string',
                        'required': False,
                    },
                    "regex": {
                        'type': 'string',
                        'required': False
                    },
                    "placeholder": {
                        'type': 'string',
                        'required': False,
                    },
                    "value": {
                        'required': False,
                        'nullable': True,
                    },
                    "helperText": {
                        'type': 'string',
                        'required': False,
                    },
                    "default": {
                        'nullable': True,
                        'empty': True
                    },
                    "options": {
                        'type': 'list',
                        'empty': True,
                        'required': False,
                        'schema': {
                            'type': 'dict',
                            'schema': {
                                "name": {
                                    'type': 'string',
                                    'required': True
                                },
                                "label": {
                                    'type': 'string',
                                    'required': True
                                },
                            }
                        }
                    },
                    "ref_types": {
                        'type': 'list',  # List of public_id of type
                        'required': False,
                        'empty': True,
                        'schema': {
                            'type': ['integer', 'list'],
                        }
                    },
                    "summaries": {
                        'type': 'list',
                        'empty': True,
                        'schema': {
                            'type': 'dict',
                            'schema': {
                                "type_id": {
                                    'type': 'integer',
                                    'required': True
                                },
                                "line": {
                                    'type': 'string',
                                    # enter curved brackets for field interpolation example: Customer IP {}
                                    'required': True
                                },
                                "label": {
                                    'type': 'string',
                                    'required': True
                                },
                                "fields": {  # List of field names
                                    'type': 'list',
                                    'empty': True,
                                    'default': [],
                                },
                                "icon": {
                                    'type': 'string',  # Free Font Awesome example: 'fa fa-cube'
                                    'required': True
                                },
                                "prefix": {
                                    'type': 'boolean',
                                    'required': False,
                                    'default': NESTED_SUMMARY_PREFIX_DEFAULT
                                }
                            }
                        }
                    }
                }
            },
        },
        'version': {
            'type': 'string',
            'default': DEFAULT_VERSION
        },
        'description': {
            'type': 'string',
            'nullable': True,
            'empty': True
        },
        'render_meta': {
            'type': 'dict',
            'allow_unknown': False,
            'schema': {
                'icon': {
                    'type': 'string',
                    'nullable': True
                },
                'sections': {
                    'type': 'list',
                    'schema': {
                        'type': 'dict',
                        'schema': {
                            "type": {  # The section kind - one of the SectionType members
                                'type': 'string',
                                'required': True,
                                # A kind outside the enum is refused here for the same reason the
                                # type IMPORT refuses it: a mistyped 'multi-data-section' is stored
                                # as a section of its own kind, read back as a plain section, and
                                # its fields are then no multi-data fields at all - silently, and
                                # only visible once an Object of the Type stores no rows for it
                                'allowed': [member.value for member in SectionType]
                            },
                            "name": {
                                'type': 'string',
                                'required': True
                            },
                            "label": {
                                'type': 'string',
                                'required': True
                            },
                            "hidden_fields": {
                                'type': 'list',
                                'required': False
                            },
                            "reference": {
                                'type': 'dict',
                                'empty': True,
                                'schema': {
                                    "type_id": {
                                        'type': 'integer',
                                        'required': True
                                    },
                                    "section_name": {
                                        'type': 'string',
                                        'required': True
                                    },
                                    'selected_fields': {
                                        'type': 'list',
                                        'empty': True
                                    }
                                }
                            },
                            'fields': {
                                'type': 'list',
                                'empty': True,
                            }
                        }
                    },
                    'empty': True
                },
                'externals': {
                    'type': 'list',
                    'schema': {
                        'type': 'dict',
                        'schema': {
                            'name': {
                                'type': 'string',
                                'required': True,
                                'empty': False,
                                'nullable': False,
                            },
                            'href': {
                                'type': 'string',  # enter curved brackets for field interpolation example: Field {}
                                'required': True
                            },
                            'label': {
                                'type': 'string',
                                'required': True,
                                'empty': False,
                                'nullable': False,
                            },
                            'icon': {
                                'type': 'string',
                                'required': True
                            },
                            'fields': {
                                'type': 'list',
                                'schema': {
                                    'type': 'string',
                                    'required': False
                                },
                                'empty': True,
                                'nullable': True,
                            }
                        }
                    },
                    'empty': True,
                },
                'summary': {
                    'type': 'dict',
                    'schema': {
                        'fields': {
                            'type': 'list',
                            'schema': {
                                'type': 'string',
                                'required': False
                            },
                            'empty': True,
                        }
                    },
                    'empty': True
                }
            }
        },
        'acl': get_type_acl_schema(),
        'ci_explorer_label': {  # Stores the name of the field which should be used as the Label in the CI Explorer
            'type': 'string',
            'required': False,
            'nullable': True,
            'empty': True,
        },
        'ci_explorer_color': {  # Stores the color which should be used in the CI Explorer representation
            'type': 'string',
            'required': False,
            'nullable': True,
            'empty': True,
        },
    }
