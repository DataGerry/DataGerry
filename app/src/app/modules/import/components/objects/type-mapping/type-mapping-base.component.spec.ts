import { DndDropEvent } from 'ngx-drag-drop';

import { TypeMappingBaseComponent } from './type-mapping-base.component';

interface MappingControl {
    name: string;
    label: string;
    type: string;
    value?: number;
}

function buildControl(name: string, type = 'field'): MappingControl {
    return { name, label: name.toUpperCase(), type };
}

function dropEventFor(control: MappingControl): DndDropEvent {
    return { data: control } as DndDropEvent;
}

/**
 * The drag and drop mapping is index based: every column of the file is one slot of `currentMapping`,
 * and dragging a control into a slot replaces it. These tests cover the moves a user can make.
 */
describe('TypeMappingBaseComponent (mapping drag and drop)', () => {
    let component: TypeMappingBaseComponent;
    let emitted: unknown[];

    beforeEach(() => {
        component = new TypeMappingBaseComponent();
        emitted = [];
        component.mappingChange.subscribe((mapping) => emitted.push(mapping));
    });

    describe('dragging a control out of a list', () => {
        it('removes the control from its source list on a move', () => {
            const name = buildControl('name');
            const available = [name, buildControl('active')];

            component.onDragged(name, available, 'move');

            expect(available.map((control) => control.name)).toEqual(['active']);
        });

        it('keeps the control in place on a copy', () => {
            const name = buildControl('name');
            const available = [name];

            component.onDragged(name, available, 'copy');

            expect(available).toEqual([name]);
        });
    });

    describe('moving a control into a column', () => {
        it('takes the control out of the available list and remembers the column index', () => {
            const name = buildControl('name');
            const available = [buildControl('public_id'), name];
            const mapping: unknown[] = [{}, {}, {}];

            component.moveControl(name, available, 1, mapping);

            expect(available.map((control) => control.name)).toEqual(['public_id']);
            expect(name.value).toBe(1);
            expect(mapping[1]).toBe(name);
            expect(mapping.length).toBe(3);
        });
    });

    describe('dropping a control on a column', () => {
        it('fills the targeted column and publishes the mapping', () => {
            const name = buildControl('name');
            component.currentMapping = [{}, {}];

            component.onDrop(dropEventFor(name), component.currentMapping, 1);

            expect(name.value).toBe(1);
            expect(component.currentMapping[1]).toBe(name);
            expect(emitted).toEqual([component.currentMapping]);
        });

        it('never grows the mapping, one column can only hold one control', () => {
            component.currentMapping = [{}, {}, {}];

            component.onDrop(dropEventFor(buildControl('name')), component.currentMapping, 2);

            expect(component.currentMapping.length).toBe(3);
        });

        it('hands the control that occupied the column back to the available list', () => {
            const previous = buildControl('active');
            const next = buildControl('name');
            const available = [next];
            component.currentMapping = [previous];

            component.onDrop(dropEventFor(next), component.currentMapping, 0, available);

            expect(component.currentMapping[0]).toBe(next);
            expect(available).toContain(previous);
        });

        it('replaces the first column when dropped without a target index', () => {
            // Documents current behaviour: the "append" branch is unreachable, an index-less drop
            // overwrites the first column instead of adding a new one.
            const first = buildControl('active');
            const next = buildControl('name');
            component.currentMapping = [first, {}];

            component.onDrop(dropEventFor(next), component.currentMapping);

            expect(component.currentMapping[0]).toBe(next);
            expect(component.currentMapping.length).toBe(2);
        });
    });

    describe('clearing a column', () => {
        it('blanks the column and publishes the mapping', () => {
            component.currentMapping = [buildControl('name'), buildControl('active')];

            component.onRemove(0, component.currentMapping);

            expect(component.currentMapping[0]).toBe('');
            expect(component.currentMapping.length).toBe(2);
            expect(emitted).toEqual([component.currentMapping]);
        });

        it('returns the removed control to the available list so it can be mapped again', () => {
            const name = buildControl('name');
            const available: unknown[] = [];
            component.currentMapping = [name];

            component.onRemove(0, component.currentMapping, available);

            expect(available).toEqual([name]);
        });

        it('does not add anything back when the column was already empty', () => {
            const available: unknown[] = [];
            component.currentMapping = [];

            component.onRemove(0, component.currentMapping, available);

            expect(available).toEqual([]);
            expect(emitted.length).toBe(1);
        });
    });
});
