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

import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { of, throwError } from 'rxjs';

import { LocationTreeOrganizerModalComponent } from './location-tree-organizer-modal.component';
import { LocationService, LocationTreeNode } from 'src/app/framework/services/location.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LocationTreeSelectNode } from '../location-tree-select/location-tree-select.model';

/* -------------------------------------------------------------------------- */
/*                                   MOCKS                                    */
/* -------------------------------------------------------------------------- */

/*
 * Fixture tree (public_id · object_id):
 *   root(1)
 *   └─ A 10·110
 *      ├─ B 11·111  (has child D)
 *      │  └─ D 12·112
 *      ├─ C 13·113  (leaf, selectable)
 *      └─ F 14·114  (leaf, NOT selectable)
 */
const node = (over: Partial<LocationTreeNode>): LocationTreeNode => ({
    public_id: 0, name: '', parent: 1, object_id: 0, type_icon: 'fas fa-cube', has_children: false, ...over
});

const CHILDREN: Record<number, LocationTreeNode[]> = {
    10: [
        node({ public_id: 11, name: 'B', parent: 10, object_id: 111, has_children: true }),
        node({ public_id: 13, name: 'C', parent: 10, object_id: 113 }),
        node({ public_id: 14, name: 'F', parent: 10, object_id: 114, type_selectable: false })
    ],
    11: [node({ public_id: 12, name: 'D', parent: 11, object_id: 112 })]
};

const dragEvent = (): DragEvent => ({
    preventDefault: () => undefined,
    clientX: 0,
    clientY: 0,
    dataTransfer: { setData: () => undefined, effectAllowed: '', dropEffect: '' }
} as unknown as DragEvent);

describe('LocationTreeOrganizerModalComponent', () => {
    let component: LocationTreeOrganizerModalComponent;
    let fixture: ComponentFixture<LocationTreeOrganizerModalComponent>;

    let locationService: jasmine.SpyObj<LocationService>;
    let toast: jasmine.SpyObj<ToastService>;

    /** A(10) loaded at root; expanded so B/C/F are present, then B expanded so D is present. */
    const buildTree = (): void => {
        locationService.getTreeRoots.and.returnValue(of([node({ public_id: 10, name: 'A', parent: 1, object_id: 110, has_children: true })]));
        locationService.getTreeChildren.and.callFake((id: number) => of(CHILDREN[id] ?? []));
        fixture.detectChanges();
        component.toggleNode(component.dataSource.data[0]);            // expand A
        component.toggleNode(component.dataSource.data[0].children$.value[0]); // expand B
    };

    const nodeA = (): LocationTreeSelectNode => component.dataSource.data[0];
    const nodeB = (): LocationTreeSelectNode => nodeA().children$.value[0];
    const nodeC = (): LocationTreeSelectNode => nodeA().children$.value[1];
    const nodeF = (): LocationTreeSelectNode => nodeA().children$.value[2];
    const nodeD = (): LocationTreeSelectNode => nodeB().children$.value[0];

    beforeEach(async () => {
        locationService = jasmine.createSpyObj<LocationService>('LocationService',
            ['getTreeRoots', 'getTreeChildren', 'searchTree', 'moveLocation', 'moveLocations', 'executedAction']);
        locationService.getTreeRoots.and.returnValue(of([]));
        locationService.getTreeChildren.and.returnValue(of([]));
        locationService.searchTree.and.returnValue(of([]));
        locationService.moveLocation.and.returnValue(of({ object_id: 0, parent: 0 }));
        locationService.moveLocations.and.returnValue(of({ object_ids: [], parent: 0 }));

        toast = jasmine.createSpyObj<ToastService>('ToastService', ['error', 'success']);

        await TestBed.configureTestingModule({
            declarations: [LocationTreeOrganizerModalComponent],
            schemas: [NO_ERRORS_SCHEMA],
            providers: [
                { provide: LocationService, useValue: locationService },
                { provide: ToastService, useValue: toast },
                { provide: NgbActiveModal, useValue: jasmine.createSpyObj('NgbActiveModal', ['close', 'dismiss']) }
            ]
        })
            // The template renders a mat-tree that is not the unit under test; skip its compilation.
            .overrideComponent(LocationTreeOrganizerModalComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(LocationTreeOrganizerModalComponent);
        component = fixture.componentInstance;
    });

    it('should create', () => {
        expect(component).toBeTruthy();
    });

    it('loads the root level on init', () => {
        locationService.getTreeRoots.and.returnValue(of([node({ public_id: 10, name: 'A', object_id: 110, has_children: true })]));
        fixture.detectChanges();

        expect(component.hasLocations).toBeTrue();
        expect(component.dataSource.data.length).toBe(1);
    });

    /* ---------------------------- DROP ELIGIBILITY ---------------------------- */

    describe('drop eligibility', () => {
        beforeEach(() => buildTree());

        it('rejects dropping a node onto itself', () => {
            component.onDragStart(dragEvent(), nodeB());
            component.onDragOver(dragEvent(), nodeB().public_id);

            expect(component.dropTargetValid).toBeFalse();
            expect(component.dropHint).toContain('own parent');
        });

        it('rejects dropping a node into its own descendant', () => {
            component.onDragStart(dragEvent(), nodeB());
            component.onDragOver(dragEvent(), nodeD().public_id);

            expect(component.dropTargetValid).toBeFalse();
            expect(component.dropHint).toContain('sub-locations');
        });

        it('rejects a target type that cannot hold children', () => {
            component.onDragStart(dragEvent(), nodeB());
            component.onDragOver(dragEvent(), nodeF().public_id);

            expect(component.dropTargetValid).toBeFalse();
            expect(component.dropHint).toContain("can't contain");
        });

        it('rejects a no-op move onto the current parent', () => {
            component.onDragStart(dragEvent(), nodeC());
            component.onDragOver(dragEvent(), nodeA().public_id);

            expect(component.dropTargetValid).toBeFalse();
            expect(component.dropHint).toContain('Already');
        });

        it('accepts a valid target and clears the hint', () => {
            component.onDragStart(dragEvent(), nodeB());
            component.onDragOver(dragEvent(), nodeC().public_id);

            expect(component.dropTargetValid).toBeTrue();
            expect(component.dropHint).toBeNull();
        });

        it('reflects drop eligibility for the current selection', () => {
            component.toggleSelect(nodeD());

            expect(component.canMoveSelectionTo(nodeC().public_id)).toBeTrue();  // D can move under C
            expect(component.canMoveSelectionTo(nodeB().public_id)).toBeFalse(); // B is D's current parent -> no-op
            expect(component.canMoveSelectionTo(component.root.public_id)).toBeTrue(); // D can move to top level
        });
    });

    /* ------------------------------- MOVING ---------------------------------- */

    describe('single move (drag)', () => {
        beforeEach(() => buildTree());

        it('moves one dragged node with moveLocation and updates the tree in place', () => {
            const a = nodeA();
            const b = nodeB();
            const c = nodeC(); // capture before the move reshuffles the arrays

            component.onDragStart(dragEvent(), b); // B not selected -> single drag
            component.onDrop(dragEvent(), c.public_id);

            expect(locationService.moveLocation).toHaveBeenCalledOnceWith(111, 13);
            expect(locationService.moveLocations).not.toHaveBeenCalled();
            expect(locationService.executedAction).toHaveBeenCalledWith('update');

            // B detached from A and attached under C — no reload
            expect(locationService.getTreeRoots).toHaveBeenCalledTimes(1);
            expect(a.children$.value.map((n) => n.public_id)).toEqual([13, 14]);
            expect(c.children$.value.map((n) => n.public_id)).toEqual([11]);
            expect(c.has_children).toBeTrue();
            expect(b.parent).toBe(13);
        });

        it('does not call the service for an invalid drop', () => {
            component.onDragStart(dragEvent(), nodeB());
            component.onDrop(dragEvent(), nodeD().public_id); // into own descendant

            expect(locationService.moveLocation).not.toHaveBeenCalled();
        });

        it('surfaces the backend message on failure and leaves the tree unchanged', () => {
            locationService.moveLocation.and.returnValue(
                throwError(() => ({ error: { message: 'would create a cycle' } }))
            );

            component.onDragStart(dragEvent(), nodeB());
            component.onDrop(dragEvent(), nodeC().public_id);

            expect(toast.error).toHaveBeenCalledWith('would create a cycle');
            expect(nodeA().children$.value.map((n) => n.public_id)).toEqual([11, 13, 14]);
            expect(component.isProcessing).toBeFalse();
        });
    });

    describe('batch move', () => {
        beforeEach(() => buildTree());

        it('moves several dragged nodes with moveLocations', () => {
            component.toggleSelect(nodeB());
            component.toggleSelect(nodeC());
            component.onDragStart(dragEvent(), nodeB()); // dragging part of the selection -> whole set
            component.onDrop(dragEvent(), component.root.public_id);

            expect(locationService.moveLocations).toHaveBeenCalledOnceWith([111, 113], 1);
            // both re-parented to the top level, A left childless
            expect(component.dataSource.data.map((n) => n.public_id)).toEqual([10, 11, 13]);
            expect(nodeA().children$.value.map((n) => n.public_id)).toEqual([14]);
        });

        it('moves the ticked rows via the keyboard "Move here" path', () => {
            component.toggleSelect(nodeB());
            component.toggleSelect(nodeC());
            component.moveSelectionTo(component.root.public_id);

            expect(locationService.moveLocations).toHaveBeenCalledOnceWith([111, 113], 1);
            expect(component.selected.size).toBe(0);
        });
    });

    describe('search-mode move', () => {
        beforeEach(() => buildTree());

        it('re-runs the search instead of a local reshuffle', fakeAsync(() => {
            // Search returns A with child B; B can validly move to the top level.
            locationService.searchTree.and.returnValue(of([
                {
                    public_id: 10, name: 'A', parent: 1, object_id: 110, icon: 'fas fa-cube',
                    children: [{ public_id: 11, name: 'B', parent: 10, object_id: 111, icon: 'fas fa-cube' }]
                }
            ]));
            component.searchString = 'B';
            tick(300);
            expect(component.inSearchMode).toBeTrue();
            const searchCallsBefore = locationService.searchTree.calls.count();

            const searchB = component.dataSource.data[0].children$.value[0];
            component.toggleSelect(searchB);
            component.moveSelectionTo(component.root.public_id);
            tick(300); // debounced re-search fired from the success handler

            expect(locationService.moveLocation).toHaveBeenCalledOnceWith(111, 1);
            expect(locationService.searchTree.calls.count()).toBe(searchCallsBefore + 1);
        }));
    });

    it('tears down cleanly on destroy', () => {
        buildTree();
        expect(() => fixture.destroy()).not.toThrow();
    });
});
