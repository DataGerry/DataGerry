# pylint: disable=invalid-name
#
# Configuration file for the Sphinx documentation builder.
#
# Layout, theme and conventions follow the OpenCelium documentation
# (docs.opencelium.io) so that both becon products read the same way.
# http://www.sphinx-doc.org/en/master/config

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath('../../'))

# -- Project information -----------------------------------------------------

project = 'DataGerry'
author = 'becon GmbH'
copyright = f'{datetime.now().year}, becon GmbH'

version = 'latest'
release = 'latest'

html_title = 'DataGerry documentation'

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.todo',
    'sphinx.ext.intersphinx',
    'sphinxcontrib.httpdomain',
    'sphinx_rtd_theme',
    'sphinx_copybutton',
    'sphinx_new_tab_link',
    'sphinxcontrib.openapi',
]

master_doc = 'index'
source_suffix = '.rst'
language = 'en'
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
pygments_style = 'sphinx'

# |year| resolves to the year the docs are built, so copyright notices in the
# content do not have to be touched every January.
#
# The edition badges mark what only exists in one way of running DataGerry.
# Use them in headings and tables; the full comparison lives in
# start/editions.
rst_epilog = """
.. |year| replace:: {year}

.. role:: badge-cloud
   :class: badge badge-cloud
.. role:: badge-selfhosted
   :class: badge badge-selfhosted
.. role:: badge-licensed
   :class: badge badge-licensed

.. |cloud| replace:: :badge-cloud:`Cloud`
.. |selfhosted| replace:: :badge-selfhosted:`Self-hosted`
.. |licensed| replace:: :badge-licensed:`Licensed feature`
""".format(year=datetime.now().year)

# -- Options for HTML output -------------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'collapse_navigation': False,
    'navigation_depth': 3,
}
html_logo = '_static/img/datagerry_logo.svg'
html_favicon = '_static/img/datagerry_favicon.png'

html_static_path = ['_static']
html_extra_path = ['api_docs']

html_css_files = [
    'css/custom.css',
]

# -- Extension configuration -------------------------------------------------

http_index_localname = 'REST API'
todo_include_todos = False
copybutton_prompt_text = r'\$ |# '
copybutton_prompt_is_regexp = True

# -- Redirects from the pre-3.3 page layout -------------------------------------
#
# The old pages are linked from the application, the Service Portal and search
# engines. Each old docname gets a small HTML page that forwards to its new home.

redirects = {
    'getting_started/welcome': 'start/introduction',
    'getting_started/cloud_vs_on_premises': 'start/editions',
    'getting_started/service_portal': 'cloud/subscriptions',
    'getting_started/dg_installation': 'operations/install',
    'getting_started/updates': 'operations/updating',
    'getting_started/administration': 'operations/configuration',
    'getting_started/license': 'about/license',
    'usage/cmdb_concepts': 'concepts/data-model',
    'usage/datagerry_assistant': 'guides/assistant',
    'usage/section_templates': 'guides/section-templates',
    'usage/multi_data_sections': 'guides/multi-data-sections',
    'usage/n_m_relations': 'guides/relations',
    'usage/ci_explorer': 'guides/ci-explorer',
    'usage/ipam': 'guides/ipam',
    'usage/locations': 'guides/locations',
    'usage/reports': 'guides/reports',
    'usage/document_generator': 'guides/generate-documents',
    'usage/isms': 'concepts/isms',
    'usage/automations': 'guides/automations',
    'usage/webhooks': 'guides/webhooks',
    'usage/imports': 'guides/import-data',
    'usage/exports': 'guides/export-data',
    'usage/file_explorer': 'guides/file-explorer',
    'usage/license_management': 'guides/license-management',
    'management/user': 'guides/users-and-groups',
    'management/user_group': 'guides/users-and-groups',
    'management/authentication': 'guides/authentication',
    'management/access_control_list': 'guides/access-control',
    'media/media': 'about/contact',
    'sources/packages': 'reference/downloads',
    'sources/docker': 'reference/downloads',
    'sources/changelog': 'reference/changelog',
    'rest_api/overview': 'reference/rest-api',
}

REDIRECT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Moved</title>
<link rel="canonical" href="{target}">
<meta http-equiv="refresh" content="0; url={target}">
</head>
<body><p>This page has moved to <a href="{target}">{target}</a>.</p></body>
</html>
"""


def write_redirects(app, exception):
    """Write a forwarding page for every old docname (HTML builders only)."""
    if exception or app.builder.format != 'html':
        return
    for old, new in redirects.items():
        if old in app.env.found_docs:
            continue  # a real page still lives there
        depth = old.count('/')
        target = '../' * depth + app.builder.get_target_uri(new)
        path = os.path.join(app.outdir, app.builder.get_target_uri(old))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as redirect_file:
            redirect_file.write(REDIRECT_TEMPLATE.format(target=target))


def setup(app):
    app.connect('build-finished', write_redirects)
# pylint: enable=invalid-name
