/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { TourStep } from './onboarding-tour.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const TYPE_ADD_ROUTE = '/framework/type/add';

export const ONBOARDING_TOUR_STEPS: TourStep[] = [
    {
        id: 'welcome',
        kind: 'intro',
        chapter: 'Product tour',
        icon: 'fas fa-compass',
        title: 'Welcome to DATAGERRY',
        text: 'DATAGERRY keeps your IT and business assets in one place. In a few minutes you will learn:',
        route: '/',
        points: [
            { title: 'Find your way', text: 'The sidebar and the search' },
            { title: 'The main menu', text: 'Framework, Toolbox and Settings' },
            { title: 'Create a type', text: 'The blueprint for one kind of asset' },
            { title: 'Add an object', text: 'Your first real asset, built from a type' }
        ]
    },
    {
        id: 'sidebar',
        kind: 'spotlight',
        chapter: 'Find your way',
        icon: 'fas fa-th-large',
        title: 'Browse by category',
        text: 'Your types are grouped into categories here. Select a type to see all of its objects. '
            + 'The Navigation tab lets you browse by location or network instead.',
        tip: 'Type into the filter at the top to find a type in a long list.',
        target: '#sidebar .sb-body',
        route: '/',
        placement: 'right'
    },
    {
        id: 'search',
        kind: 'spotlight',
        chapter: 'Find your way',
        icon: 'fas fa-search',
        title: 'Find anything',
        text: 'Search all of your objects by any value, from every page.',
        tip: 'Press Tab to turn a term into a filter tag, or pick a type or category from the suggestions '
            + 'to narrow the results.',
        target: '[data-tour="search"]',
        route: '/',
        placement: 'bottom'
    },
    {
        id: 'framework',
        kind: 'spotlight',
        chapter: 'The main menu',
        icon: 'fas fa-map',
        title: 'Your data model',
        text: 'The Framework menu holds the building blocks of your CMDB:',
        features: [
            {
                icon: 'fas fa-vector-square',
                title: 'Objects',
                text: 'Every asset, across all types',
                right: 'base.framework.object.view'
            },
            {
                icon: 'fas fa-object-group',
                title: 'Types',
                text: 'Blueprints that define the fields of an asset',
                right: 'base.framework.type.view'
            },
            {
                icon: 'fas fa-folder-open',
                title: 'Categories',
                text: 'Group your types in the sidebar',
                right: 'base.framework.category.view'
            },
            {
                icon: 'fas fa-exchange-alt',
                title: 'Relations',
                text: 'Define how objects link, such as a server to its rack',
                right: 'base.framework.relation.view'
            }
        ],
        tip: 'Section Templates save a set of fields once for reuse in many types. '
            + 'Changing a global template updates every type that uses it.',
        target: '[data-tour="framework"]',
        route: '/',
        right: 'base.framework.type.view',
        placement: 'bottom'
    },
    {
        id: 'toolbox',
        kind: 'spotlight',
        chapter: 'The main menu',
        icon: 'fas fa-th',
        title: 'Tools for your daily work',
        text: 'Your everyday tools for working with the data in your CMDB:',
        features: [
            {
                icon: 'fas fa-file-import',
                title: 'Importer',
                text: 'Bring in assets from CSV or JSON',
                right: 'base.import.*'
            },
            {
                icon: 'fas fa-project-diagram',
                title: 'CI Explorer',
                text: 'See how your assets depend on each other',
                right: 'base.framework.ciExplorer.view'
            },
            {
                icon: 'fas fa-chart-line',
                title: 'Reporting',
                text: 'Answer questions about your assets',
                right: 'base.framework.report.view'
            },
            {
                icon: 'fas fa-file-export',
                title: 'Exporter',
                text: 'Share data with other tools',
                right: 'base.export.*'
            }
        ],
        tip: 'Webhooks, the Document Generator, ISMS and more are in the Toolbox too.',
        target: '[data-tour="toolbox"]',
        route: '/',
        placement: 'bottom'
    },
    {
        id: 'settings',
        kind: 'spotlight',
        chapter: 'The main menu',
        icon: 'fas fa-cog',
        title: 'Settings and administration',
        text: 'Configure the system, manage your license, users, groups and their access, and review the object logs.',
        tip: 'Rights belong to groups. Add a user to a group to give them its access.',
        target: '[data-tour="settings"]',
        route: '/',
        placement: 'bottom'
    },
    {
        id: 'open-types',
        kind: 'spotlight',
        chapter: 'Create a type',
        icon: 'fas fa-object-group',
        title: 'Open your types',
        text: 'A type is the blueprint for one kind of asset, such as a server or a laptop. '
            + 'Open Framework and select Types to see all of your types.',
        illustration: 'framework-menu',
        tip: 'Select Add on the Types page to start the type wizard.',
        target: '[data-tour="framework"]',
        route: '/',
        right: 'base.framework.type.view',
        placement: 'bottom'
    },
    {
        id: 'type-steps',
        kind: 'spotlight',
        chapter: 'Create a type',
        icon: 'fas fa-list-ol',
        title: 'Four steps to a type',
        text: 'The type wizard walks you through each step:',
        points: [
            { title: 'Basic information', text: 'Name, label and icon' },
            { title: 'Content', text: 'The sections and fields of its objects' },
            { title: 'Meta', text: 'Summary fields and the CI Explorer label' },
            { title: 'ACL', text: 'Which groups can access its objects' }
        ],
        tip: 'Save the type once every step in the validation list is valid.',
        target: '#type-builder ul.steps-indicator',
        route: TYPE_ADD_ROUTE,
        right: 'base.framework.type.add',
        placement: 'bottom'
    },
    {
        id: 'type-content',
        kind: 'spotlight',
        chapter: 'Create a type',
        icon: 'fas fa-th-list',
        title: 'Add sections and fields',
        text: 'In the Content step, drag a Section from the palette onto the form, then drop fields into it.',
        illustration: 'type-content',
        tip: 'A Reference field links to objects of another type, for example a server to its rack.',
        target: '#type-builder ul.steps-indicator li:nth-child(2) > a',
        include: '.step-indicator',
        route: TYPE_ADD_ROUTE,
        right: 'base.framework.type.add',
        placement: 'bottom'
    },
    {
        id: 'add-object',
        kind: 'spotlight',
        chapter: 'Add an object',
        icon: 'fas fa-plus',
        title: 'Add your first object',
        text: 'With a type in place, you can add real assets. Select Add new Object here, from any page.',
        tip: 'In the object list of a type, Add opens the form with that type already selected.',
        target: '[data-tour="add-object"]',
        route: '/',
        right: 'base.framework.object.add',
        placement: 'right'
    },
    {
        id: 'object-type',
        kind: 'spotlight',
        chapter: 'Add an object',
        icon: 'fas fa-cube',
        title: 'Pick a type and fill in the form',
        text: 'Choose the type of the new object and select Add. '
            + 'The form is built from the sections and fields of that type.',
        illustration: 'object-form',
        tip: 'Fill in the required fields, then select Save to create the object.',
        target: 'cmdb-object-add form',
        route: '/framework/object/add',
        right: 'base.framework.object.add',
        placement: 'bottom'
    },
    {
        id: 'finish',
        kind: 'outro',
        chapter: 'Tour complete',
        icon: 'fas fa-check',
        title: "You're all set",
        text: 'You know how to find your way, create a type and add an object. A good next step:',
        route: '/',
        actions: [
            {
                icon: 'fas fa-cube',
                title: 'Add your first object',
                text: 'Create a record for one of your types',
                route: '/framework/object/add',
                right: 'base.framework.object.add'
            },
            {
                icon: 'fas fa-object-group',
                title: 'Create another type',
                text: 'Open the type wizard',
                route: TYPE_ADD_ROUTE,
                right: 'base.framework.type.add'
            },
            {
                icon: 'fas fa-file-import',
                title: 'Import existing data',
                text: 'Bring in your assets from CSV or JSON',
                route: '/import',
                right: 'base.import.*'
            },
            {
                icon: 'fas fa-book',
                title: 'Read the documentation',
                text: 'Guides for every feature',
                href: 'https://docs.datagerry.com'
            }
        ]
    }
];
