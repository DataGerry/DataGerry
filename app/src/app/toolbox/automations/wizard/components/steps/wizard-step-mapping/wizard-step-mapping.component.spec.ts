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
    AutomationMappingSource,
    AutomationValueTransform,
    createEmptyAutomationDefinition,
    hasActiveTransform
} from '../../../models/automation-definition.model';
import { describeValuePath, SequenceBinding, ValueSource } from '../wizard-step-flow/wizard-step-flow.component';
import { WizardStepMappingComponent } from './wizard-step-mapping.component';
/* ------------------------------------------------------------------------------------------------------------------ */

function entry(targetPath: string, ...fields: string[]): AutomationMappingEntry {
    return {
        target: targetPath,
        sources: fields.map(field => ({ field, origin: 'auto' as const, confidence: 1 }))
    };
}


/** One value the sequence writes: the call that writes it, the path it lands on, what it reads. */
function binding(callIndex: string, call: string, path: string, ...fields: string[]): SequenceBinding {
    return {
        key: `${callIndex}:${path}`,
        call,
        callIndex,
        path,
        field: path.split('.').pop() ?? path,
        sources: fields.map(field => ({
            label: field,
            reference: answer(field),
            call: 'DataGerry \u00b7 read objects'
        }))
    };
}


/** A component on an automation that writes into the target system, already through its check. */
function sending(bindings: SequenceBinding[], adjustments: Record<string, AutomationValueTransform> = {}): {
    component: WizardStepMappingComponent;
    definition: AutomationDefinition;
} {
    const component = new WizardStepMappingComponent();
    const definition = createEmptyAutomationDefinition();

    definition.adjustments = adjustments;

    component.definition = definition;
    component.sourceFields = ['hostname', 'serial', 'location']
        .map(name => ({ name, label: name.toUpperCase(), type: 'text' }));
    component.sequenceBindings = bindings;
    component.ngDoCheck();

    return { component, definition };
}


/** An answer of an earlier call, spelled the way the sequence spells its references. */
function answer(name: string): string {
    return `#FFCFB5.(response).body.$.results[i].${name}`;
}


function offered(name: string, group = 'Zabbix \u00b7 list hosts'): ValueSource {
    const label = `results[*].${name}`;

    return { group, label, reference: answer(name), ...describeValuePath(label) };
}


function writes(target: string, source: Partial<AutomationMappingSource>): AutomationMappingEntry {
    return { target, sources: [{ field: '', origin: 'manual', confidence: 1, ...source }] };
}


/** A component on an automation that writes into DataGerry, already through its first check. */
function writing(mapping: AutomationMappingEntry[] = [], sources = [offered('hostname'), offered('serial')]): {
    component: WizardStepMappingComponent;
    definition: AutomationDefinition;
} {
    const component = new WizardStepMappingComponent();
    const definition = createEmptyAutomationDefinition();

    definition.direction = 'incoming';
    definition.mapping = mapping;

    component.definition = definition;
    component.objectTypeFields = ['hostname', 'serial', 'location']
        .map(name => ({ name, label: name.toUpperCase(), type: 'text' }));
    component.valueSources = sources;
    component.ngDoCheck();

    return { component, definition };
}


describe('WizardStepMappingComponent', () => {

    describe('the values the sequence writes', () => {

        it('shows one row per value the sequence writes', () => {
            const { component } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname'),
                binding('1_1', 'i-doit \u00b7 add category', 'params.data.sysid', 'serial')
            ]);

            expect(component.bindingRows.map(row => row.path))
                .toEqual(['params.data.title', 'params.data.sysid']);
        });


        /* The bug this view was rebuilt for: the calls the user added wrote fields nobody could see. */
        it('shows the values of every call, not only the ones an old mapping guessed', () => {
            const { component, definition } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname'),
                binding('1_1', 'i-doit \u00b7 add category', 'params.data.sysid', 'serial'),
                binding('1_2', 'i-doit \u00b7 add contact', 'params.data.room', 'location')
            ]);

            definition.mapping = [entry('params.data.title', 'hostname')];
            component.ngDoCheck();

            expect(component.bindingRows.length).toBe(3);
        });


        /* Two calls can write the same path, so a row that does not name its call says nothing. */
        it('puts the rows under the call that writes them', () => {
            const { component } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.sysid', 'serial'),
                binding('1_1', 'i-doit \u00b7 add category', 'params.data.sysid', 'hostname'),
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')
            ]);

            expect(component.bindingGroups.map(group => group.call))
                .toEqual(['i-doit \u00b7 create object', 'i-doit \u00b7 add category']);
            expect(component.bindingGroups[0].rows.map(row => row.field)).toEqual(['sysid', 'title']);
        });


        it('names the target field by the last segment of the path it lands on', () => {
            const { component } = sending([binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')]);

            expect(component.bindingRows[0].field).toBe('title');
        });


        it('names the sources of a combined value in the order the script sees them', () => {
            const { component } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.sysid', 'serial', 'location')
            ]);
            const row = component.bindingRows[0];

            expect(row.combined).toBeTrue();
            expect(row.sources.map(source => source.variable)).toEqual(['value1', 'value2']);
            expect(row.sources.map(source => source.label)).toEqual(['serial', 'location']);
        });


        it('calls the single source of a plain copy just value', () => {
            const { component } = sending([binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')]);

            expect(component.bindingRows[0].combined).toBeFalse();
            expect(component.bindingRows[0].sources[0].variable).toBe('value');
        });


        /* The name is what fits in the row; the route it stands for is one hover away. */
        it('keeps the whole route behind the name a source is shown by', () => {
            const { component } = sending([binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')]);

            expect(component.bindingRows[0].sources[0].reference).toBe(answer('hostname'));
        });


        it('counts the values that combine and the values that adjust', () => {
            const { component } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.sysid', 'serial', 'location'),
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')
            ], { '1_0:params.data.sysid': { enabled: true, script: 'value = value1 + value2;' } });

            expect(component.combinedCount).toBe(1);
            expect(component.adjustedCount).toBe(1);
        });


        /* An empty draft is a row somebody opened and left, not an adjustment the automation runs. */
        it('does not count an adjustment with nothing in it', () => {
            const { component } = sending(
                [binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')],
                { '1_0:params.data.title': { enabled: true, script: '   ' } }
            );

            expect(component.adjustedCount).toBe(0);
        });


        /* Nothing on this screen belongs to the direction that writes DataGerry. */
        it('builds no object type rows for an automation that reads DataGerry', () => {
            const { component } = sending([binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')]);

            expect(component.incoming).toBeFalse();
            expect(component.writeRows).toEqual([]);
        });
    });


    describe('adjusting a value on its way out', () => {

        it('opens with an empty draft the user can type into', () => {
            const { component, definition } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')
            ]);

            component.onAdjustmentToggled(component.bindingRows[0]);

            expect(component.isExpanded('1_0:params.data.title')).toBeTrue();
            expect(definition.adjustments).toEqual({ '1_0:params.data.title': { enabled: true, script: '' } });
        });


        it('keeps what was typed into it', () => {
            const { component, definition } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')
            ]);

            component.onAdjustmentToggled(component.bindingRows[0]);
            component.ngDoCheck();
            component.onAdjustmentScriptChanged(component.bindingRows[0], 'value = value.trim();');
            component.ngDoCheck();

            expect(definition.adjustments['1_0:params.data.title'].script).toBe('value = value.trim();');
            expect(component.bindingRows[0].adjusted).toBeTrue();
        });


        /* Two calls can write the same path, and an adjustment belongs to exactly one of them. */
        it('leaves the same path on another call alone', () => {
            const { component, definition } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.sysid', 'serial'),
                binding('1_1', 'i-doit \u00b7 add category', 'params.data.sysid', 'hostname')
            ]);

            component.onAdjustmentScriptChanged(component.bindingRows[0], 'value = value.trim();');

            expect(Object.keys(definition.adjustments)).toEqual(['1_0:params.data.sysid']);
        });


        /* Switching it off is not the same as throwing it away - the script has to survive. */
        it('remembers the script of an adjustment that was switched off', () => {
            const { component, definition } = sending(
                [binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')],
                { '1_0:params.data.title': { enabled: true, script: 'value = 1;' } }
            );

            component.onAdjustmentEnabledChanged(component.bindingRows[0], false);

            expect(definition.adjustments['1_0:params.data.title'])
                .toEqual({ enabled: false, script: 'value = 1;' });
        });


        it('removing it leaves the row without any adjustment at all', () => {
            const { component, definition } = sending(
                [binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')],
                { '1_0:params.data.title': { enabled: true, script: 'value = 1;' } }
            );

            component.onAdjustmentRemoved(component.bindingRows[0]);

            expect('1_0:params.data.title' in definition.adjustments).toBeFalse();
            expect(component.isExpanded('1_0:params.data.title')).toBeFalse();
        });


        /* An adjustment folded away is an adjustment nobody reviews, and reviewing is the point. */
        it('shows an adjustment the automation already carries', () => {
            const { component } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname'),
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.note', 'serial')
            ], { '1_0:params.data.title': { enabled: true, script: 'value = 1;' } });

            expect(component.isExpanded('1_0:params.data.title')).toBeTrue();
            expect(component.isExpanded('1_0:params.data.note')).toBeFalse();
        });


        it('leaves an adjustment the user folded away folded', () => {
            const { component } = sending(
                [binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')],
                { '1_0:params.data.title': { enabled: true, script: 'value = 1;' } }
            );

            component.onAdjustmentToggled(component.bindingRows[0]);
            component.sequenceBindings = [...component.sequenceBindings];
            component.ngDoCheck();

            expect(component.isExpanded('1_0:params.data.title')).toBeFalse();
        });


        /* Which value feeds which field is settled where the request value gets its reference. */
        it('never changes what the sequence writes where', () => {
            const { component, definition } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')
            ]);

            component.onAdjustmentToggled(component.bindingRows[0]);
            component.onAdjustmentScriptChanged(component.bindingRows[0], 'value = value.trim();');
            component.onAdjustmentRemoved(component.bindingRows[0]);

            expect(definition.mapping).toEqual([]);
            expect(component.bindingRows.map(row => row.path)).toEqual(['params.data.title']);
        });
    });


    describe('conditions', () => {

        it('adds a rule on the first source field', () => {
            const { component, definition } = sending([]);

            component.onAddRule();

            expect(definition.conditions.rules).toEqual([
                { field: 'hostname', operator: 'equals', value: '' }
            ]);
        });


        /* An operator that compares against nothing must not carry a value nobody can see. */
        it('drops the value when the comparison stops needing one', () => {
            const { component, definition } = sending([]);

            component.onAddRule();
            component.onRuleValueChanged(0, 'srv-1');
            component.onRuleOperatorChanged(0, 'is_empty');

            expect(definition.conditions.rules[0].value).toBe('');
        });
    });


    describe('the object type it writes into', () => {

        /* Deciding means seeing the fields that stay empty as much as the ones that fill up. */
        it('gives every field of the object type a row, written or not', () => {
            const { component } = writing([writes('hostname', { reference: answer('hostname') })]);

            expect(component.writeRows.map(row => row.field)).toEqual(['hostname', 'serial', 'location']);
        });


        it('leaves a field nobody writes standing on nothing', () => {
            const { component } = writing();

            expect(component.writeRows.map(row => row.choice)).toEqual(['', '', '']);
            expect(component.writeRows.every(row => row.entry === null)).toBeTrue();
        });


        it('counts the fields that are given a value', () => {
            const { component } = writing([
                writes('hostname', { reference: answer('hostname') }),
                writes('serial', { literal: 'unknown' })
            ]);

            expect(component.writtenCount).toBe(2);
            expect(component.writeRows.length).toBe(3);
        });


        /* Under the object as well as under the call: a call answers with more paths than a
           dropdown can be read through, and they differ at the far end of a long path. */
        it('offers the answers under the call that gave them, and the object they sit on', () => {
            const { component } = writing([], [
                offered('hostname'),
                offered('serial'),
                offered('room', 'i-doit \u00b7 read location')
            ]);

            expect(component.valueGroups.map(group => group.name)).toEqual([
                'Zabbix \u00b7 list hosts \u00b7 results[*]',
                'i-doit \u00b7 read location \u00b7 results[*]'
            ]);
            expect(component.valueGroups[0].items.length).toBe(2);
            // The row itself carries the name alone; the route is in the heading above it.
            expect(component.valueGroups[0].items.map(source => source.leaf))
                .toEqual(['hostname', 'serial']);
        });


        /* Nothing on this screen belongs to the direction that reads DataGerry. */
        it('shows no rows for the values a sequence writes elsewhere', () => {
            const { component } = writing([writes('hostname', { reference: answer('hostname') })]);

            expect(component.bindingRows).toEqual([]);
            expect(component.bindingGroups).toEqual([]);
        });
    });


    describe('deciding what a field is given', () => {

        it('writes an answer of an earlier call into the field it was picked for', () => {
            const { component, definition } = writing();

            component.onWriteChoiceChanged(component.writeRows[0], answer('hostname'));

            expect(definition.mapping).toEqual([
                { target: 'hostname', sources: [{ field: '', origin: 'manual', confidence: 1, reference: answer('hostname') }] }
            ]);
        });


        it('writes a value the user types in', () => {
            const { component, definition } = writing();

            component.onWriteChoiceChanged(component.writeRows[2], component.literalChoice);
            component.ngDoCheck();
            component.onWriteLiteralChanged(component.writeRows[2], 'Frankfurt');

            expect(definition.mapping[0].sources[0].literal).toBe('Frankfurt');
            expect(component.writeRows[2].choice).toBe(component.literalChoice);
        });


        /* A field takes one value, so picking again is a correction rather than a second source. */
        it('replaces the value of a field instead of adding a second one', () => {
            const { component, definition } = writing([writes('hostname', { literal: 'srv-1' })]);

            component.onWriteChoiceChanged(component.writeRows[0], answer('serial'));

            expect(definition.mapping.length).toBe(1);
            expect(definition.mapping[0].sources).toEqual([
                { field: '', origin: 'manual', confidence: 1, reference: answer('serial') }
            ]);
        });


        /* Not being written is the absence of an entry, which is what the mapping means elsewhere. */
        it('takes the field out of the automation when it is given nothing', () => {
            const { component, definition } = writing([writes('hostname', { reference: answer('hostname') })]);

            component.onWriteChoiceChanged(component.writeRows[0], '');

            expect(definition.mapping).toEqual([]);
        });


        it('shows a picked answer by its field name, with the whole route behind it', () => {
            const { component } = writing([writes('hostname', { reference: answer('serial') })]);
            const tokens = component.writeRows[0].tokens;

            expect(tokens.map(token => token.label)).toEqual(['serial']);
            expect(tokens[0].text).toBe(answer('serial'));
        });


        /* A call the user moved must not silently unset the fields it fed. */
        it('keeps standing on an answer the sequence no longer offers', () => {
            const { component } = writing([writes('hostname', { reference: answer('gone') })]);

            expect(component.writeRows[0].choice).toBe(answer('gone'));
            expect(component.writeRows[0].unlisted).toBe('gone');
        });
    });


    describe('adjusting a value on its way into DataGerry', () => {

        it('adjusts the field the value lands in', () => {
            const { component, definition } = writing([writes('hostname', { reference: answer('hostname') })]);

            component.onToggleTransform(definition.mapping[0]);
            component.onTransformScriptChanged(definition.mapping[0], 'value = value.trim();');

            expect(component.isExpanded('hostname')).toBeTrue();
            expect(hasActiveTransform(definition.mapping[0])).toBeTrue();
        });


        /* An adjustment without a value to adjust is not an adjustment anybody could run. */
        it('drops the adjustment together with the value it adjusted', () => {
            const { component, definition } = writing([
                { ...writes('hostname', { literal: 'srv-1' }), transform: { enabled: true, script: 'value = 1;' } }
            ]);

            component.onWriteChoiceChanged(component.writeRows[0], '');

            expect(definition.mapping).toEqual([]);
            expect(component.isExpanded('hostname')).toBeFalse();
        });
    });


    describe('what it hands the template', () => {

        /* A fresh array every check makes the pickers rebuild, which is what once locked the step up. */
        it('hands out the same rows until an input actually changes', () => {
            const { component } = writing([writes('hostname', { literal: 'srv-1' })]);
            const rows = component.writeRows;

            component.ngDoCheck();
            component.ngDoCheck();

            expect(component.writeRows).toBe(rows);
        });


        it('leaves the picker options alone while only the mapping changes', () => {
            const { component } = writing();
            const groups = component.valueGroups;

            component.onWriteChoiceChanged(component.writeRows[0], answer('hostname'));
            component.ngDoCheck();

            expect(component.valueGroups).toBe(groups);
            expect(component.writeRows[0].choice).toBe(answer('hostname'));
        });


        /* Same reason as the write rows: a fresh array makes every row rebuild for nothing. */
        it('hands out the same rows the sequence writes until an input actually changes', () => {
            const { component } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')
            ]);
            const rows = component.bindingRows;
            const groups = component.bindingGroups;

            component.ngDoCheck();
            component.ngDoCheck();

            expect(component.bindingRows).toBe(rows);
            expect(component.bindingGroups).toBe(groups);
        });


        /* Stored somewhere no array of the definition covers, so the check has to watch it too. */
        it('rebuilds the rows when an adjustment is stored', () => {
            const { component } = sending([
                binding('1_0', 'i-doit \u00b7 create object', 'params.data.title', 'hostname')
            ]);

            component.onAdjustmentScriptChanged(component.bindingRows[0], 'value = value.trim();');
            component.ngDoCheck();

            expect(component.bindingRows[0].adjusted).toBeTrue();
            expect(component.bindingRows[0].transform?.script).toBe('value = value.trim();');
        });
    });
});
