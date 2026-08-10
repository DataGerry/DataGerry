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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {
    AutomationDefinition,
    AutomationRuleOperator,
    AutomationTriggerType,
    isTriggerSupported,
    requiresMatching,
    ruleNeedsValue
} from './automation-definition.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The wizard's step structure.
 *
 * The concept describes eight logical steps; they are presented as five groups, so related choices
 * stay on one page as numbered sections. The mapping is fixed here so the stepper, the validation and
 * the summary panel all agree on it.
 */
export enum WizardGroup {
    TRIGGER = 0,
    DATA = 1,
    TARGET = 2,
    MAPPING = 3,
    REVIEW = 4
}

/** Number of visible groups - used for bounds checks when navigating. */
export const WIZARD_GROUP_COUNT = 5;

export interface WizardGroupDescriptor {
    group: WizardGroup;
    title: string;
    subtitle: string;
    icon: string;

    /** The logical steps from the concept that this group covers, for the stepper's tooltip. */
    logicalSteps: string[];
}

export const WIZARD_GROUPS: ReadonlyArray<WizardGroupDescriptor> = [
    {
        group: WizardGroup.TRIGGER,
        title: 'Trigger',
        subtitle: 'When should the automation start?',
        icon: 'fas fa-bolt',
        logicalSteps: ['Trigger']
    },
    {
        group: WizardGroup.DATA,
        title: 'Data',
        subtitle: 'Which data should be used?',
        icon: 'fas fa-database',
        logicalSteps: ['Object type', 'Fields']
    },
    {
        group: WizardGroup.TARGET,
        title: 'Target system',
        subtitle: 'Where should it go?',
        icon: 'fas fa-share-nodes',
        logicalSteps: ['Target system', 'Action']
    },
    {
        group: WizardGroup.MAPPING,
        title: 'Assignment',
        subtitle: 'How should fields be matched?',
        icon: 'fas fa-right-left',
        logicalSteps: ['Field mapping', 'Conditions']
    },
    {
        group: WizardGroup.REVIEW,
        title: 'Review',
        subtitle: 'Check and activate',
        icon: 'fas fa-circle-check',
        logicalSteps: ['Test', 'Summary']
    }
];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                  TRIGGER CHOICES                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

export interface TriggerChoice {
    type: AutomationTriggerType;
    title: string;
    description: string;
    icon: string;

    /** False for triggers the compiler cannot translate yet - shown but not selectable. */
    available: boolean;
}

/**
 * The trigger cards, in the order the mockup shows them.
 *
 * Object events and webhooks are advertised so users can see where the feature is heading, but the
 * concept defers them ("Webhook bitte noch nicht") and the compiler rejects them.
 */
export const TRIGGER_CHOICES: ReadonlyArray<TriggerChoice> = [
    {
        type: 'manual',
        title: 'Start manually',
        description: 'The automation is started by a user.',
        icon: 'fas fa-play',
        available: isTriggerSupported('manual')
    },
    {
        type: 'object_created',
        title: 'Object created',
        description: 'Runs whenever a new object is created.',
        icon: 'fas fa-file-circle-plus',
        available: isTriggerSupported('object_created')
    },
    {
        type: 'object_updated',
        title: 'Object updated',
        description: 'Runs whenever an object is updated.',
        icon: 'fas fa-pen',
        available: isTriggerSupported('object_updated')
    },
    {
        type: 'scheduled',
        title: 'Scheduled',
        description: 'Runs at a defined time or interval.',
        icon: 'fas fa-clock',
        available: isTriggerSupported('scheduled')
    },
    {
        type: 'webhook',
        title: 'Webhook',
        description: 'Triggered by an external webhook.',
        icon: 'fas fa-plug',
        available: isTriggerSupported('webhook')
    }
];

/** Rule operators with the labels the visual builder shows. */
export const RULE_OPERATOR_CHOICES: ReadonlyArray<{ value: AutomationRuleOperator; label: string }> = [
    { value: 'equals', label: 'is' },
    { value: 'not_equals', label: 'is not' },
    { value: 'contains', label: 'contains' },
    { value: 'not_contains', label: 'does not contain' },
    { value: 'starts_with', label: 'starts with' },
    { value: 'ends_with', label: 'ends with' },
    { value: 'is_empty', label: 'is empty' },
    { value: 'is_not_empty', label: 'is not empty' },
    { value: 'greater_than', label: 'is greater than' },
    { value: 'less_than', label: 'is less than' }
];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     VALIDATION                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Whether a group has everything it needs, so the wizard knows when "Next" may be enabled.
 *
 * Deliberately separate from AutomationCompilerService.validate(): this governs navigation and must
 * stay cheap, while the compiler's validation is the authoritative gate before saving.
 */
export function isGroupComplete(group: WizardGroup, definition: AutomationDefinition): boolean {
    switch (group) {
        case WizardGroup.TRIGGER:
            return !!definition.name.trim()
                && isTriggerSupported(definition.trigger.type)
                && (definition.trigger.type !== 'scheduled' || !!definition.trigger.cronExp.trim());

        case WizardGroup.DATA:
            return !!definition.objectType.typeId && definition.fields.length > 0;

        case WizardGroup.TARGET:
            return !!definition.target.connectorId && !!definition.target.operation;

        case WizardGroup.MAPPING:
            return definition.mapping.some(entry => !!entry.target)
                && (!requiresMatching(definition) || !!definition.matching.identifyBy)
                && definition.conditions.rules.every(rule => !!rule.field
                    && (!ruleNeedsValue(rule.operator) || !!rule.value.trim()));

        case WizardGroup.REVIEW:
            return true;

        default:
            return false;
    }
}


/** The first group that is still incomplete, or REVIEW when everything is done. */
export function firstIncompleteGroup(definition: AutomationDefinition): WizardGroup {
    for (const descriptor of WIZARD_GROUPS) {
        if (!isGroupComplete(descriptor.group, definition)) {
            return descriptor.group;
        }
    }

    return WizardGroup.REVIEW;
}


/**
 * How far the user may navigate: one past the last complete group.
 *
 * Reviewing earlier choices stays possible while skipping ahead over an unfinished group does not.
 */
export function furthestReachableGroup(definition: AutomationDefinition): WizardGroup {
    const firstGap = firstIncompleteGroup(definition);

    return Math.min(firstGap, WIZARD_GROUP_COUNT - 1) as WizardGroup;
}
