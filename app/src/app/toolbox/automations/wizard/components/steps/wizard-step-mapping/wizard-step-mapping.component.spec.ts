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
    AutomationMappingEntry,
    createEmptyAutomationDefinition,
    hasActiveTransform
} from '../../../models/automation-definition.model';
import { TargetField } from '../../../models/target-catalog.model';
import { WizardStepMappingComponent } from './wizard-step-mapping.component';
/* ------------------------------------------------------------------------------------------------------------------ */

function target(path: string): TargetField {
    return { path, name: path.split('.').pop() ?? path, type: 'string' };
}


function entry(targetPath: string, ...fields: string[]): AutomationMappingEntry {
    return {
        target: targetPath,
        sources: fields.map(field => ({ field, origin: 'auto' as const, confidence: 1 }))
    };
}


function adjusted(base: AutomationMappingEntry, script: string): AutomationMappingEntry {
    return { ...base, transform: { enabled: true, script } };
}


/** A component wired the way the wizard shell wires it, already through its first check. */
function mounted(mapping: AutomationMappingEntry[], sources = ['hostname', 'serial', 'location']): {
    component: WizardStepMappingComponent;
    definition: AutomationDefinition;
} {
    const component = new WizardStepMappingComponent();
    const definition = createEmptyAutomationDefinition();

    definition.mapping = mapping;

    component.definition = definition;
    component.sourceFields = sources.map(name => ({ name, label: name.toUpperCase(), type: 'text' }));
    component.targetFields = [target('params.title'), target('params.sysid'), target('params.note')];
    component.ngDoCheck();

    return { component, definition };
}


describe('WizardStepMappingComponent', () => {

    describe('the mapping it shows', () => {

        it('shows one row per target field the automation writes', () => {
            const { component } = mounted([entry('params.title', 'hostname'), entry('params.note', 'serial')]);

            expect(component.rows.map(row => row.target)).toEqual(['params.title', 'params.note']);
        });


        it('names the target field the way the target system names it', () => {
            const { component } = mounted([entry('params.title', 'hostname')]);

            expect(component.rows[0].targetName).toBe('title');
        });


        /* The whole point of keying by target: two fields feeding one is an ordinary row. */
        it('names the sources of a combined field in the order the script sees them', () => {
            const { component } = mounted([entry('params.sysid', 'serial', 'location')]);
            const row = component.rows[0];

            expect(row.combined).toBeTrue();
            expect(row.sources.map(source => source.variable)).toEqual(['value1', 'value2']);
            expect(row.sources.map(source => source.field)).toEqual(['serial', 'location']);
        });


        /* The script refers to the sources by name, so a name has to say which field it stands for. */
        it('says which field each variable of a combined row stands for', () => {
            const { component } = mounted([entry('params.sysid', 'serial', 'location')]);

            expect(component.rows[0].sources.map(source => `${source.variable}=${source.label}`))
                .toEqual(['value1=SERIAL', 'value2=LOCATION']);
        });


        it('calls the single source of a plain copy just value', () => {
            const { component } = mounted([entry('params.title', 'hostname')]);

            expect(component.rows[0].combined).toBeFalse();
            expect(component.rows[0].sources[0].variable).toBe('value');
        });


        it('lists the source fields that reach no target field', () => {
            const { component } = mounted([entry('params.title', 'hostname')]);

            expect(component.spares.map(field => field.name)).toEqual(['serial', 'location']);
        });


        it('counts the rows that combine and the rows that adjust', () => {
            const { component } = mounted([
                adjusted(entry('params.sysid', 'serial', 'location'), 'value = value1 + value2;'),
                entry('params.title', 'hostname')
            ]);

            expect(component.combinedCount).toBe(1);
            expect(component.adjustedCount).toBe(1);
        });


        /* An empty draft is a row somebody opened and left, not an adjustment the automation runs. */
        it('does not count an adjustment with nothing in it', () => {
            const { component } = mounted([adjusted(entry('params.title', 'hostname'), '   ')]);

            expect(component.adjustedCount).toBe(0);
        });
    });


    describe('what it leaves to the sequence', () => {

        /* Which field goes where is settled where the request value gets its reference. */
        it('never changes which source feeds which target', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onToggleTransform(definition.mapping[0]);
            component.onTransformScriptChanged(definition.mapping[0], 'value = value.trim();');
            component.onRemoveTransform(definition.mapping[0]);

            expect(definition.mapping.length).toBe(1);
            expect(definition.mapping[0].target).toBe('params.title');
            expect(definition.mapping[0].sources.map(source => source.field)).toEqual(['hostname']);
        });


        it('leaves the fields nobody sends where they are', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onToggleTransform(definition.mapping[0]);

            expect(definition.unmapped).toEqual([]);
            expect(component.spares.map(field => field.name)).toEqual(['serial', 'location']);
        });
    });


    describe('the value adjustment', () => {

        it('opens with an empty draft the user can type into', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onToggleTransform(definition.mapping[0]);

            expect(component.isExpanded('params.title')).toBeTrue();
            expect(definition.mapping[0].transform).toEqual({ enabled: true, script: '' });
        });


        it('keeps what was typed into it', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onToggleTransform(definition.mapping[0]);
            component.onTransformScriptChanged(definition.mapping[0], 'value = value.toUpperCase();');

            expect(hasActiveTransform(definition.mapping[0])).toBeTrue();
            expect(definition.mapping[0].transform?.script).toBe('value = value.toUpperCase();');
        });


        /* Switching it off is not the same as throwing it away - the script has to survive. */
        it('remembers the script of an adjustment that was switched off', () => {
            const { component, definition } = mounted([adjusted(entry('params.title', 'hostname'), 'value = 1;')]);

            component.onTransformEnabledChanged(definition.mapping[0], false);

            expect(hasActiveTransform(definition.mapping[0])).toBeFalse();
            expect(definition.mapping[0].transform?.script).toBe('value = 1;');
        });


        it('removing it leaves the row without any adjustment at all', () => {
            const { component, definition } = mounted([adjusted(entry('params.title', 'hostname'), 'value = 1;')]);

            component.onRemoveTransform(definition.mapping[0]);

            expect('transform' in definition.mapping[0]).toBeFalse();
            expect(component.isExpanded('params.title')).toBeFalse();
        });


        /* An adjustment folded away is an adjustment nobody reviews, and reviewing is the point. */
        it('shows an adjustment the automation already carries', () => {
            const { component } = mounted([
                adjusted(entry('params.title', 'hostname'), 'value = 1;'),
                entry('params.note', 'serial')
            ]);

            expect(component.isExpanded('params.title')).toBeTrue();
            expect(component.isExpanded('params.note')).toBeFalse();
        });


        it('leaves an adjustment the user folded away folded', () => {
            const { component, definition } = mounted([adjusted(entry('params.title', 'hostname'), 'value = 1;')]);

            component.onToggleTransform(definition.mapping[0]);
            definition.mapping = [...definition.mapping];
            component.ngDoCheck();

            expect(component.isExpanded('params.title')).toBeFalse();
        });
    });


    describe('conditions', () => {

        it('adds a rule on the first source field', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onAddRule();

            expect(definition.conditions.rules).toEqual([
                { field: 'hostname', operator: 'equals', value: '' }
            ]);
        });


        /* An operator that compares against nothing must not carry a value nobody can see. */
        it('drops the value when the comparison stops needing one', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onAddRule();
            component.onRuleValueChanged(0, 'srv-1');
            component.onRuleOperatorChanged(0, 'is_empty');

            expect(definition.conditions.rules[0].value).toBe('');
        });
    });
});
