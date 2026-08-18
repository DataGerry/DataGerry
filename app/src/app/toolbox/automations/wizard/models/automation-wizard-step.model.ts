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
    ruleNeedsValue
} from './automation-definition.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The wizard's step structure.
 *
 * Five groups, and which choices sit in which is not arbitrary. The two ends of an automation are
 * one step because they are one decision - what is joined to what - and DataGerry's end carries its
 * object type and fields there rather than in a step of its own, since the assistant builds that
 * side itself. What the target system does then gets a step to be read, and the fields a step to be
 * matched.
 */
export enum WizardGroup {
    TRIGGER = 0,
    LINK = 1,
    FLOW = 2,
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
        group: WizardGroup.LINK,
        title: 'Connection',
        subtitle: 'Which systems?',
        icon: 'fas fa-share-nodes',
        logicalSteps: ['Object type', 'Fields', 'Target system', 'Action']
    },
    {
        group: WizardGroup.FLOW,
        title: 'Sequence',
        subtitle: 'What happens there?',
        icon: 'fas fa-list-ol',
        logicalSteps: ['Lookup', 'Branches']
    },
    {
        group: WizardGroup.MAPPING,
        title: 'Fields',
        subtitle: 'What arrives where?',
        icon: 'fas fa-right-left',
        logicalSteps: ['Field mapping', 'Value adjustment', 'Conditions']
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

        // Both ends at once: the step holds both poles, so neither alone finishes it.
        case WizardGroup.LINK:
            return !!definition.objectType.typeId
                && definition.fields.length > 0
                && !!definition.target.connectorId;

        // Nothing to fill in - the sequence follows from the connection.
        case WizardGroup.FLOW:
            return true;

        // The assignment itself happens in the sequence, so nothing here has to be filled in
        // before moving on - only a half-written condition can hold the step back.
        case WizardGroup.MAPPING:
            return definition.conditions.rules.every(rule => !!rule.field
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
