# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
The schema of a CmdbType
"""
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_VERSION = '1.0.0'

# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_type_schema() -> dict:
    """
    Returns the CmdbTypeSchema

    Returns:
        dict: Schema of the CmdbType
    """
    return {
        'public_id': { # public_id of the CmdbType
            'type': 'integer'
        },
        'name': { # Unique name of the CmdbType
            'type': 'string',
            'required': True,
            'regex': r'(\w+)-*(\w)([\w-]*)'  # kebab case validation,
        },
        'label': { # Label of the CmdbType (visible by users)
            'type': 'string',
            'required': False
        },
        'author_id': { # public_id of the CmdbUser who created this CmdbType
            'type': 'integer',
            'required': True
        },
        'editor_id': { # public_id of the CmdbUser who last edited this CmdbType
            'type': 'integer',
            'nullable': True,
            'required': False
        },
        'creation_time': { # The datetime when this CmdbType was created
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'last_edit_time': { # The datetime when the last editing of this CmdbType occured
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'selectable_as_parent': { # If True, this location is selectable as a parent location for other locations
            'type': 'boolean',
            'default': True
        },
        'global_template_ids':{ # The public_id's of global CmdbSectionTemplates used by this CmdbType
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'string',
            }
        },
        'active': { # If True, this CmdbType is active
            'type': 'boolean',
            'required': False,
            'default': True
        },
        'fields': {
            'type': 'list',
            'required': True,
            'min': 1,
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
                                },
                                "icon": {
                                    'type': 'string',  # Free Font Awesome example: 'fa fa-cube'
                                    'required': True
                                },
                                "prefix": {
                                    'type': 'boolean',
                                    'required': False,
                                    'default': True
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
            'required': True,
            'schema': {
                'icon': {
                    'type': 'string',
                    'nullable': True
                },
                'sections': {
                    'type': 'list',
                    'required': True,
                    'min': 1,
                    'schema': {
                        'type': 'dict',
                        'schema': {
                            "type": {
                                'type': 'string',
                                'required': True
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
                                'required': True
                            },
                            'href': {
                                'type': 'string',  # enter curved brackets for field interpolation example: Field {}
                                'required': True
                            },
                            'label': {
                                'type': 'string',
                                'required': True
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
        'acl': {
            'type': 'dict',
            'allow_unknown': True,
            'required': False,
        },
        'ci_explorer_label': { # Stores the name of the field which should be used as the Label in the CI Explorer
            'type': 'string',
            'required': False,
            'nullable': True,
            'empty': True,
        },
        'ci_explorer_color': { # Stores the color which should be used in the CI Explorer representation
            'type': 'string',
            'required': False,
            'nullable': True,
            'empty': True,
        },
    }
