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


function entry(targetPath: string, ...fields: string[]): AutomationMappingEntry {
    return {
        target: targetPath,
        sources: fields.map(field => ({ field, origin: 'auto' as const, confidence: 1 }))
    };
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
    component.matchableTargets = ['title', 'sysid'];
    component.ngDoCheck();

    return { component, definition };
}


describe('WizardStepMappingComponent', () => {

    describe('rows', () => {

        it('shows one row per target field', () => {
            const { component } = mounted([entry('params.title', 'hostname'), entry('params.note', 'serial')]);

            expect(component.rows.map(row => row.target)).toEqual(['params.title', 'params.note']);
        });


        /* The whole point of keying by target: two fields feeding one is an ordinary row. */
        it('names the sources of a combined field in the order the script sees them', () => {
            const { component } = mounted([entry('params.sysid', 'serial', 'location')]);
            const row = component.rows[0];

            expect(row.combined).toBeTrue();
            expect(row.sources.map(source => source.variable)).toEqual(['value1', 'value2']);
            expect(row.sources.map(source => source.field)).toEqual(['serial', 'location']);
        });


        it('calls the single source of a plain copy just value', () => {
            const { component } = mounted([entry('params.title', 'hostname')]);

            expect(component.rows[0].combined).toBeFalse();
            expect(component.rows[0].sources[0].variable).toBe('value');
        });


        it('lists the source fields that feed nothing', () => {
            const { component } = mounted([entry('params.title', 'hostname')]);

            expect(component.spares.map(field => field.name)).toEqual(['serial', 'location']);
        });
    });


    describe('editing', () => {

        it('adding a source turns a plain copy into a combination', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onAddSource('params.title', 'serial');

            expect(definition.mapping[0].sources.map(source => source.field)).toEqual(['hostname', 'serial']);
        });


        it('moving a source is what decides value1 from value2', () => {
            const { component, definition } = mounted([entry('params.sysid', 'serial', 'location')]);

            component.onMoveSource('params.sysid', 'location', -1);

            expect(definition.mapping[0].sources.map(source => source.field)).toEqual(['location', 'serial']);
        });


        it('removing the last source removes the row, not just the value', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onRemoveSource('params.title', 'hostname');

            expect(definition.mapping).toEqual([]);
        });


        /* Otherwise the next suggestion would hand back the field the user just took away. */
        it('remembers a source that was taken away', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onRemoveSource('params.title', 'hostname');

            expect(definition.unmapped).toEqual(['hostname']);
        });


        it('assigning a spare to a free target opens a row', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onAssign('serial', 'params.note');

            expect(definition.mapping[1]).toEqual(jasmine.objectContaining({ target: 'params.note' }));
            expect(definition.mapping[1].sources[0].field).toBe('serial');
        });


        it('assigning a spare to a taken target joins it', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onAssign('serial', 'params.title');

            expect(definition.mapping.length).toBe(1);
            expect(definition.mapping[0].sources.map(source => source.field)).toEqual(['hostname', 'serial']);
        });
    });


    describe('target choices', () => {

        /*
         * Bound into ng-select, which rebuilds its panel whenever it is handed a new items array.
         * Building them in the template returned a fresh array on every change detection run, which
         * locked the step up; this pins the caching that replaced it.
         */
        it('returns the same array while nothing changes', () => {
            const { component } = mounted([entry('params.title', 'hostname')]);
            const first = component.targetChoices('params.title');

            component.ngDoCheck();
            component.ngDoCheck();

            expect(component.targetChoices('params.title')).toBe(first);
        });


        it('blocks a target another row already writes to', () => {
            const { component } = mounted([entry('params.title', 'hostname'), entry('params.note', 'serial')]);
            const blocked = component.targetChoices('params.title').find(choice => choice.path === 'params.note');

            expect(blocked?.disabled).toBeTrue();
        });


        it('leaves a row its own target selectable', () => {
            const { component } = mounted([entry('params.title', 'hostname')]);
            const own = component.targetChoices('params.title').find(choice => choice.path === 'params.title');

            expect(own?.disabled).toBeFalse();
        });
    });


    describe('identification', () => {

        it('offers the marker only where the lookup can search', () => {
            const { component } = mounted([entry('params.title', 'hostname'), entry('params.note', 'serial')]);

            expect(component.rows[0].canIdentify).toBeTrue();
            expect(component.rows[1].canIdentify).toBeFalse();
        });


        /* A combined field has no single value to search by, so it cannot identify anything. */
        it('refuses a combined field as the identifier', () => {
            const { component } = mounted([entry('params.title', 'hostname', 'serial')]);

            expect(component.rows[0].canIdentify).toBeFalse();
        });


        it('marks and unmarks the identifying row', () => {
            const { component, definition } = mounted([entry('params.title', 'hostname')]);

            component.onIdentifyBy(component.rows[0]);
            expect(definition.matching.identifyBy).toBe('hostname');

            component.ngDoCheck();
            component.onIdentifyBy(component.rows[0]);
            expect(definition.matching.identifyBy).toBe('');
        });
    });
});
