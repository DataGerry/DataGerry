import { SimpleChange, SimpleChanges } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TypePreviewComponent } from './type-preview.component';
import { ImportTypeAction, ImportTypeEntry } from '../../../models/import-type.models';

function buildEntry(name: string, label?: string): ImportTypeEntry {
    return { name, label: label ?? name, fields: [] };
}

function typesChange(currentValue: ImportTypeEntry[]): SimpleChanges {
    return { types: new SimpleChange(undefined, currentValue, false) };
}

function actionChange(currentValue: ImportTypeAction): SimpleChanges {
    return { action: new SimpleChange('create', currentValue, false) };
}

/**
 * The review step lists the uploaded types, lets the user search them and remove single entries.
 * The removal must always point back into the upload, also while a search is narrowing the list.
 */
describe('TypePreviewComponent (type import - review step)', () => {
    let component: TypePreviewComponent;
    let fixture: ComponentFixture<TypePreviewComponent>;

    /** Binds an upload the way the wizard host does. */
    const bindTypes = (types: ImportTypeEntry[]) => {
        component.types = types;
        component.ngOnChanges(typesChange(types));
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [TypePreviewComponent]
        })
            .overrideComponent(TypePreviewComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypePreviewComponent);
        component = fixture.componentInstance;
        component.ngOnInit();
    });

    afterEach(() => component.ngOnDestroy());

    describe('listing the upload', () => {
        it('shows one row per uploaded type', () => {
            bindTypes([buildEntry('server', 'Server'), buildEntry('router', 'Router')]);

            expect(component.rows.map((row) => row.label)).toEqual(['Server', 'Router']);
            expect(component.visibleRows.length).toBe(2);
        });

        it('shows nothing for an empty upload', () => {
            bindTypes([]);

            expect(component.rows).toEqual([]);
            expect(component.visibleRows).toEqual([]);
        });

        it('rebuilds the list when another file was uploaded', () => {
            bindTypes([buildEntry('server', 'Server')]);

            bindTypes([buildEntry('router', 'Router'), buildEntry('switch', 'Switch')]);

            expect(component.rows.map((row) => row.label)).toEqual(['Router', 'Switch']);
        });
    });

    describe('searching the upload', () => {
        beforeEach(() => bindTypes([
            buildEntry('web_server', 'Web Server'),
            buildEntry('router', 'Router'),
            buildEntry('switch', 'Network Switch')
        ]));

        it('narrows the list to the matching types', () => {
            component.searchControl.setValue('router');

            expect(component.visibleRows.map((row) => row.name)).toEqual(['router']);
        });

        it('restores the full list when the search is cleared', () => {
            component.searchControl.setValue('router');

            component.searchControl.setValue('');

            expect(component.visibleRows.length).toBe(3);
        });

        it('keeps the search applied when the same upload is re-bound', () => {
            component.searchControl.setValue('router');

            component.ngOnChanges(typesChange(component.types));

            expect(component.visibleRows.map((row) => row.name)).toEqual(['router']);
        });

        it('shows an empty list when nothing matches', () => {
            component.searchControl.setValue('firewall');

            expect(component.visibleRows).toEqual([]);
        });
    });

    describe('choosing the action', () => {
        it('publishes the action the user picked', () => {
            const emitted: ImportTypeAction[] = [];
            component.actionChange.subscribe((action) => emitted.push(action));

            component.actionControl.setValue('update');

            expect(emitted).toEqual(['update']);
        });

        it('adopts the action the host binds without echoing it back', () => {
            const emitted: ImportTypeAction[] = [];
            component.actionChange.subscribe((action) => emitted.push(action));

            component.action = 'update';
            component.ngOnChanges(actionChange('update'));

            expect(component.actionControl.value).toBe('update');
            expect(emitted).toEqual([]);
        });

        it('leaves the control alone when the bound action already matches', () => {
            const emitted: ImportTypeAction[] = [];
            component.actionControl.setValue('update');
            component.action = 'update';
            component.actionChange.subscribe((action) => emitted.push(action));

            component.ngOnChanges(actionChange('update'));

            expect(emitted).toEqual([]);
        });
    });

    describe('removing a type', () => {
        beforeEach(() => bindTypes([
            buildEntry('web_server', 'Web Server'),
            buildEntry('router', 'Router'),
            buildEntry('switch', 'Network Switch')
        ]));

        it('reports the position of the removed type in the upload', () => {
            const emitted: number[] = [];
            component.typeRemoved.subscribe((index) => emitted.push(index));

            component.onRemoveType(component.visibleRows[1]);

            expect(emitted).toEqual([1]);
        });

        it('reports the upload position, not the position in the filtered list', () => {
            const emitted: number[] = [];
            component.typeRemoved.subscribe((index) => emitted.push(index));
            component.searchControl.setValue('switch');

            component.onRemoveType(component.visibleRows[0]);

            expect(emitted).toEqual([2]);
        });
    });

    describe('leaving the step', () => {
        it('stops publishing after the step was destroyed', () => {
            const emitted: ImportTypeAction[] = [];
            component.actionChange.subscribe((action) => emitted.push(action));

            component.ngOnDestroy();
            component.actionControl.setValue('update');

            expect(emitted).toEqual([]);
        });
    });
});
