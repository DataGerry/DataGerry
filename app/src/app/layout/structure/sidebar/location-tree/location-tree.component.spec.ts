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
import { Router } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';

import { LocationTreeComponent } from './location-tree.component';
import { LocationService, LocationTreeNode, LocationTreeSearchNode } from 'src/app/framework/services/location.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

/* -------------------------------------------------------------------------- */
/*                                   MOCKS                                    */
/* -------------------------------------------------------------------------- */

const rootNode = (over: Partial<LocationTreeNode> = {}): LocationTreeNode => ({
    public_id: 10,
    name: 'Data Center Berlin',
    parent: 1,
    object_id: 42,
    type_icon: 'fas fa-building',
    has_children: true,
    ...over
});

const searchResult = (): LocationTreeSearchNode[] => ([
    {
        public_id: 9893,
        name: 'Datacenter',
        parent: 1,
        object_id: 5001,
        icon: 'fas fa-cube',
        children: [
            {
                public_id: 9894,
                name: 'Rack-01',
                parent: 9893,
                object_id: 5002,
                icon: 'fas fa-cube',
                children: [
                    { public_id: 9895, name: 'Server-alpha', parent: 9894, object_id: 5003, icon: 'fas fa-server' }
                ]
            }
        ]
    }
]);

describe('LocationTreeComponent', () => {
    let component: LocationTreeComponent;
    let fixture: ComponentFixture<LocationTreeComponent>;

    let locationService: jasmine.SpyObj<LocationService> & { locationActionSource: Subject<unknown> };
    let objectService: { objectActionSource: Subject<unknown> };
    let router: jasmine.SpyObj<Router>;
    let toast: jasmine.SpyObj<ToastService>;

    beforeEach(async () => {
        locationService = jasmine.createSpyObj<LocationService>('LocationService',
            ['getTreeRoots', 'getTreeChildren', 'searchTree']) as jasmine.SpyObj<LocationService> & { locationActionSource: Subject<unknown> };
        locationService.locationActionSource = new Subject();
        locationService.getTreeRoots.and.returnValue(of([]));
        locationService.getTreeChildren.and.returnValue(of([]));
        locationService.searchTree.and.returnValue(of([]));

        objectService = { objectActionSource: new Subject() };
        router = jasmine.createSpyObj<Router>('Router', ['navigateByUrl']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['error']);

        await TestBed.configureTestingModule({
            declarations: [LocationTreeComponent],
            schemas: [NO_ERRORS_SCHEMA],
            providers: [
                { provide: LocationService, useValue: locationService },
                { provide: ObjectService, useValue: objectService },
                { provide: Router, useValue: router },
                { provide: ToastService, useValue: toast }
            ]
        })
            // The template renders a mat-tree that is not the unit under test; skip its compilation.
            .overrideComponent(LocationTreeComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(LocationTreeComponent);
        component = fixture.componentInstance;
    });

    it('should create', () => {
        expect(component).toBeTruthy();
    });

    /* --------------------------------- BROWSE --------------------------------- */

    describe('browse mode', () => {
        it('loads the root level on init and maps type_icon to icon', () => {
            locationService.getTreeRoots.and.returnValue(of([rootNode()]));

            fixture.detectChanges();

            expect(locationService.getTreeRoots).toHaveBeenCalledTimes(1);
            expect(component.hasLocations).toBeTrue();
            expect(component.inSearchMode).toBeFalse();
            expect(component.dataSource.data.length).toBe(1);
            expect(component.dataSource.data[0].icon).toBe('fas fa-building');
            expect(component.dataSource.data[0].has_children).toBeTrue();
            expect(component.dataSource.data[0].loaded).toBeFalse();
        });

        it('flags an empty tree', () => {
            locationService.getTreeRoots.and.returnValue(of([]));

            fixture.detectChanges();

            expect(component.hasLocations).toBeFalse();
        });

        it('shows an error message when the root load fails', () => {
            locationService.getTreeRoots.and.returnValue(throwError(() => new Error('boom')));

            fixture.detectChanges();

            expect(component.errorMessage).toContain("couldn't load the locations");
            expect(component.hasLocations).toBeFalse();
        });

        it('lazily loads children on first expand and caches them', () => {
            locationService.getTreeRoots.and.returnValue(of([rootNode()]));
            locationService.getTreeChildren.and.returnValue(of([
                rootNode({ public_id: 20, name: 'Room 1.01', parent: 10, object_id: 55, has_children: false })
            ]));
            fixture.detectChanges();

            const node = component.dataSource.data[0];
            component.toggleNode(node);

            expect(locationService.getTreeChildren).toHaveBeenCalledOnceWith(10);
            expect(node.loaded).toBeTrue();
            expect(node.children$.value.length).toBe(1);
            expect(node.children$.value[0].name).toBe('Room 1.01');
            expect(component.treeControl.isExpanded(node)).toBeTrue();

            // Collapse then re-expand must not trigger another request
            component.toggleNode(node);
            expect(component.treeControl.isExpanded(node)).toBeFalse();
            component.toggleNode(node);
            expect(component.treeControl.isExpanded(node)).toBeTrue();
            expect(locationService.getTreeChildren).toHaveBeenCalledTimes(1);
        });

        it('shows a toast and stops the spinner when a child load fails', () => {
            locationService.getTreeRoots.and.returnValue(of([rootNode()]));
            locationService.getTreeChildren.and.returnValue(throwError(() => new Error('boom')));
            fixture.detectChanges();

            const node = component.dataSource.data[0];
            component.toggleNode(node);

            expect(toast.error).toHaveBeenCalled();
            expect(node.loading).toBeFalse();
            expect(component.treeControl.isExpanded(node)).toBeFalse();
        });

        it('reloads the root level on an object action while browsing', () => {
            locationService.getTreeRoots.and.returnValue(of([rootNode()]));
            fixture.detectChanges();
            expect(locationService.getTreeRoots).toHaveBeenCalledTimes(1);

            objectService.objectActionSource.next('create');

            expect(locationService.getTreeRoots).toHaveBeenCalledTimes(2);
        });
    });

    /* --------------------------------- SEARCH --------------------------------- */

    describe('search mode', () => {
        beforeEach(() => {
            locationService.getTreeRoots.and.returnValue(of([rootNode()]));
            fixture.detectChanges();
        });

        it('searches (debounced) and renders the result fully expanded', fakeAsync(() => {
            locationService.searchTree.and.returnValue(of(searchResult()));

            component.searchString = 'alpha';
            tick(300);

            expect(locationService.searchTree).toHaveBeenCalledOnceWith('alpha');
            expect(component.inSearchMode).toBeTrue();
            expect(component.isSearching).toBeFalse();
            expect(component.hasSearchResults).toBeTrue();

            const root = component.dataSource.data[0];
            const child = root.children$.value[0];
            const leaf = child.children$.value[0];
            expect(root.icon).toBe('fas fa-cube');
            expect(root.has_children).toBeTrue();
            expect(leaf.name).toBe('Server-alpha');
            expect(leaf.has_children).toBeFalse();
            expect(component.treeControl.isExpanded(root)).toBeTrue();
            expect(component.treeControl.isExpanded(child)).toBeTrue();
        }));

        it('debounces and cancels superseded queries', fakeAsync(() => {
            locationService.searchTree.and.returnValue(of(searchResult()));

            component.searchString = 'a';
            tick(100);
            component.searchString = 'al';
            tick(100);
            component.searchString = 'alpha';
            tick(300);

            expect(locationService.searchTree).toHaveBeenCalledOnceWith('alpha');
        }));

        it('trims the query and ignores whitespace-only input', fakeAsync(() => {
            locationService.searchTree.and.returnValue(of(searchResult()));

            component.searchString = '   ';
            tick(300);

            expect(locationService.searchTree).not.toHaveBeenCalled();
        }));

        it('flags no results', fakeAsync(() => {
            locationService.searchTree.and.returnValue(of([]));

            component.searchString = 'zzz';
            tick(300);

            expect(component.inSearchMode).toBeTrue();
            expect(component.hasSearchResults).toBeFalse();
        }));

        it('shows an error message when the search fails', fakeAsync(() => {
            locationService.searchTree.and.returnValue(throwError(() => new Error('boom')));

            component.searchString = 'alpha';
            tick(300);

            expect(component.errorMessage).toContain("couldn't complete the location search");
            expect(component.isSearching).toBeFalse();
        }));

        it('returns to the browse tree when the search is cleared', fakeAsync(() => {
            locationService.searchTree.and.returnValue(of(searchResult()));
            component.searchString = 'alpha';
            tick(300);
            expect(component.inSearchMode).toBeTrue();

            const rootLoadsBefore = locationService.getTreeRoots.calls.count();
            component.handleSearchReset();
            tick(300);

            expect(component.inSearchMode).toBeFalse();
            expect(locationService.getTreeRoots.calls.count()).toBe(rootLoadsBefore + 1);
        }));
    });

    /* ------------------------------- NAVIGATION ------------------------------- */

    it('navigates to the clicked location object', () => {
        component.onLocationElementClicked(5003);

        expect(component.selectedLocationID).toBe(5003);
        expect(router.navigateByUrl).toHaveBeenCalledWith('/framework/object/view/5003');
    });

    it('tears down cleanly on destroy', () => {
        locationService.getTreeRoots.and.returnValue(of([rootNode()]));
        fixture.detectChanges();

        expect(() => fixture.destroy()).not.toThrow();
    });
});
