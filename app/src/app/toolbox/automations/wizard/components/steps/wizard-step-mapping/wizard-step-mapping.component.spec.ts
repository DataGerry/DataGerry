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
    createEmptyAutomationDefinition
} from '../../../models/automation-definition.model';
import { TargetField } from '../../../models/target-catalog.model';
import { WizardStepMappingComponent } from './wizard-step-mapping.component';
/* ------------------------------------------------------------------------------------------------------------------ */

function target(path: string): TargetField {
    return { path, name: path.split('.').pop() ?? path, type: 'string' };
}


function entry(source: string, mappedTo = ''): AutomationMappingEntry {
    return { source, target: mappedTo, origin: 'auto', confidence: mappedTo ? 1 : 0 };
}


/** A component wired the way the wizard shell wires it, already through its first check. */
function mountedComponent(mapping: AutomationMappingEntry[]): {
    component: WizardStepMappingComponent;
    definition: AutomationDefinition;
} {
    const component = new WizardStepMappingComponent();
    const definition = createEmptyAutomationDefinition();

    definition.mapping = mapping;

    component.definition = definition;
    component.sourceFields = mapping.map(item => ({
        name: item.source,
        label: item.source.toUpperCase(),
        type: 'text'
    }));
    component.targetFields = [target('title'), target('description')];
    component.ngDoCheck();

    return { component, definition };
}


describe('WizardStepMappingComponent', () => {

    describe('target choices', () => {

        it('offers every target field of the action', () => {
            const { component } = mountedComponent([entry('hostname')]);

            expect(component.targetChoices('hostname').map(choice => choice.path))
                .toEqual(['title', 'description']);
        });


        /*
         * The dropdowns are bound into ng-select, which rebuilds its panel whenever it is handed a
         * new items array. Building the choices in the template returned a fresh array on every
         * change detection run, which locked the step up; this pins the caching that replaced it.
         */
        it('returns the same array while nothing changes', () => {
            const { component } = mountedComponent([entry('hostname'), entry('serial')]);
            const first = component.targetChoices('hostname');

            component.ngDoCheck();
            component.ngDoCheck();

            expect(component.targetChoices('hostname')).toBe(first);
        });


        it('rebuilds once the mapping changed', () => {
            const { component } = mountedComponent([entry('hostname'), entry('serial')]);
            const before = component.targetChoices('serial');

            component.onTargetSelected('hostname', 'title');
            component.ngDoCheck();

            expect(component.targetChoices('serial')).not.toBe(before);
        });


        it('rebuilds once the target fields changed', () => {
            const { component } = mountedComponent([entry('hostname')]);
            const before = component.targetChoices('hostname');

            component.targetFields = [target('title')];
            component.ngDoCheck();

            expect(component.targetChoices('hostname')).not.toBe(before);
            expect(component.targetChoices('hostname').map(choice => choice.path)).toEqual(['title']);
        });


        it('blocks a target another pair already writes to, naming the pair', () => {
            const { component } = mountedComponent([entry('hostname', 'title'), entry('serial')]);
            const blocked = component.targetChoices('serial').find(choice => choice.path === 'title');

            expect(blocked?.disabled).toBeTrue();
            expect(blocked?.label).toContain('HOSTNAME');
        });


        it('leaves a pair its own target selectable', () => {
            const { component } = mountedComponent([entry('hostname', 'title'), entry('serial')]);
            const own = component.targetChoices('hostname').find(choice => choice.path === 'title');

            expect(own?.disabled).toBeFalse();
            expect(own?.label).toBe('title');
        });


        it('answers with an empty list for a source it does not know', () => {
            const { component } = mountedComponent([entry('hostname')]);

            expect(component.targetChoices('unknown')).toEqual([]);
            expect(component.targetChoices('unknown')).toBe(component.targetChoices('other'));
        });
    });


    describe('visible rows', () => {

        it('shows every pair by default, as the mapping array itself', () => {
            const { component, definition } = mountedComponent([entry('hostname', 'title'), entry('serial')]);

            expect(component.visibleMapping).toBe(definition.mapping);
        });


        it('narrows to the open pairs when the filter is switched on', () => {
            const { component } = mountedComponent([entry('hostname', 'title'), entry('serial')]);

            component.showOnlyUnresolved = true;
            component.ngDoCheck();

            expect(component.visibleMapping.map(row => row.source)).toEqual(['serial']);
        });


        it('keeps the filtered rows stable while nothing changes', () => {
            const { component } = mountedComponent([entry('hostname', 'title'), entry('serial')]);

            component.showOnlyUnresolved = true;
            component.ngDoCheck();

            const rows = component.visibleMapping;
            component.ngDoCheck();

            expect(component.visibleMapping).toBe(rows);
        });
    });


    describe('counts', () => {

        it('separates matched, open and adjusted pairs', () => {
            const { component, definition } = mountedComponent([
                entry('hostname', 'title'),
                entry('serial', 'description'),
                entry('note')
            ]);

            definition.mapping[0].transform = { enabled: true, script: 'value = value.trim();' };

            expect(component.resolvedCount).toBe(2);
            expect(component.unresolvedCount).toBe(1);
            expect(component.adjustedCount).toBe(1);
        });
    });
});
