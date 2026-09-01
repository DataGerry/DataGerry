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

import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { Router } from '@angular/router';
import { Subject, of } from 'rxjs';

import { IpamTreeComponent } from './ipam-tree.component';
import { IpamTreeService } from './services/ipam-tree.service';
import { IpamTreeNode, IpamTreeResponse } from './models/ipam-tree.types';
import { ObjectService } from 'src/app/framework/services/object.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';

/* -------------------------------------------------------------------------- */
/*                                   MOCKS                                    */
/* -------------------------------------------------------------------------- */

const supernet = (over: Partial<IpamTreeNode> = {}): IpamTreeNode => ({
    public_id: 70,
    name: 'Corporate',
    cidr: '10.0.0.0/8',
    type: 'ipv4',
    has_children: true,
    ...over
});

const subnet = (over: Partial<IpamTreeNode> = {}): IpamTreeNode => ({
    public_id: 71,
    name: 'Office Berlin',
    cidr: '10.1.0.0/16',
    type: 'ipv4',
    has_children: false,
    ...over
});

const tree = (over: Partial<IpamTreeResponse> = {}): IpamTreeResponse => ({
    supernets: [supernet()],
    unassigned: [],
    ...over
});

/* -------------------------------------------------------------------------- */

describe('IpamTreeComponent', () => {
    let component: IpamTreeComponent;
    let fixture: ComponentFixture<IpamTreeComponent>;

    let ipamTreeService: jasmine.SpyObj<IpamTreeService>;
    let objectService: { objectActionSource: Subject<unknown> };
    let sidebarService: { reloaded: Subject<boolean> };
    let router: jasmine.SpyObj<Router>;

    beforeEach(async () => {
        ipamTreeService = jasmine.createSpyObj<IpamTreeService>('IpamTreeService',
            ['getTree', 'getSupernetChildren']);
        // Built per call: every read returns fresh nodes, so a node mutated by an expand cannot leak
        // into the next read the way a single shared response object would.
        ipamTreeService.getTree.and.callFake(() => of(tree()));
        ipamTreeService.getSupernetChildren.and.callFake(() => of({ children: [subnet()] }));

        objectService = { objectActionSource: new Subject() };
        sidebarService = { reloaded: new Subject<boolean>() };
        router = jasmine.createSpyObj<Router>('Router', ['navigateByUrl']);

        await TestBed.configureTestingModule({
            declarations: [IpamTreeComponent],
            schemas: [NO_ERRORS_SCHEMA],
            providers: [
                { provide: IpamTreeService, useValue: ipamTreeService },
                { provide: ObjectService, useValue: objectService },
                { provide: SidebarService, useValue: sidebarService },
                { provide: Router, useValue: router }
            ]
        })
            // The template renders a mat-tree that is not the unit under test; skip its compilation.
            .overrideComponent(IpamTreeComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(IpamTreeComponent);
        component = fixture.componentInstance;
    });

    it('should create', () => {
        expect(component).toBeTruthy();
    });

    it('reads the tree once on init', () => {
        fixture.detectChanges();

        expect(ipamTreeService.getTree).toHaveBeenCalledTimes(1);
        expect(component.hasSupernets).toBeTrue();
    });

    /* --------------------------------- REFRESH -------------------------------- */

    describe('refresh', () => {
        it('re-reads the tree when a network object was written', fakeAsync(() => {
            fixture.detectChanges();

            objectService.objectActionSource.next('create');
            tick(200);

            expect(ipamTreeService.getTree).toHaveBeenCalledTimes(2);
        }));

        it('re-reads the tree when the sidebar is refreshed', fakeAsync(() => {
            fixture.detectChanges();

            sidebarService.reloaded.next(true);
            tick(200);

            expect(ipamTreeService.getTree).toHaveBeenCalledTimes(2);
        }));

        it('re-reads once for a save that announces itself more than once', fakeAsync(() => {
            fixture.detectChanges();

            // One object save patches the object, writes its active state and refreshes the sidebar.
            objectService.objectActionSource.next('update');
            tick(30);
            sidebarService.reloaded.next(true);
            tick(30);
            objectService.objectActionSource.next('update');
            tick(200);

            expect(ipamTreeService.getTree).toHaveBeenCalledTimes(2);
        }));

        it('keeps the tree on screen while re-reading', fakeAsync(() => {
            fixture.detectChanges();

            let visibleWhileReading = true;
            ipamTreeService.getTree.and.callFake(() => {
                visibleWhileReading = !component.isLoadingTree;
                return of(tree());
            });

            objectService.objectActionSource.next('update');
            tick(200);

            expect(visibleWhileReading).toBeTrue();
        }));

        it('re-opens the branches that were open before the re-read', fakeAsync(() => {
            fixture.detectChanges();

            const node = component.supernetDataSource.data[0];
            component.onToggleSupernet(node);
            expect(component.isNodeExpanded(node)).toBeTrue();
            expect(ipamTreeService.getSupernetChildren).toHaveBeenCalledTimes(1);

            // The re-read replaces the node objects, so their children have to be fetched again.
            objectService.objectActionSource.next('update');
            tick(200);

            const reloaded = component.supernetDataSource.data[0];
            expect(ipamTreeService.getSupernetChildren).toHaveBeenCalledTimes(2);
            expect(component.isNodeExpanded(reloaded)).toBeTrue();
            expect(reloaded.children?.length).toBe(1);
        }));

        it('leaves collapsed branches unread after a re-read', fakeAsync(() => {
            fixture.detectChanges();

            objectService.objectActionSource.next('update');
            tick(200);

            expect(ipamTreeService.getSupernetChildren).not.toHaveBeenCalled();
        }));
    });
});
