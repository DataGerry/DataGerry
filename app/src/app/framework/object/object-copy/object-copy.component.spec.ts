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
import { Component, Input, NO_ERRORS_SCHEMA, TemplateRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { NgTemplateOutlet } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';

import { BehaviorSubject, of } from 'rxjs';

import { ObjectCopyComponent } from './object-copy.component';
import { CheckboxComponent } from 'src/app/core/components/base/checkbox/checkbox.component';
import { PermissionLinkDirective } from 'src/app/modules/auth/directives/permission-link.directive';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { AclPermissionService } from 'src/app/modules/auth/services/acl-permission.service';
import { ObjectService } from '../../services/object.service';
import { TypeService } from '../../services/type.service';
import { LocationService } from '../../services/location.service';
import { UserService } from '../../../management/services/user.service';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { PortsLicenseService } from '../object-view/ports-overview/services/ports-license.service';
import { PortsAccess } from '../object-view/ports-overview/models/ports-license.types';
import { PORT_ADD_RIGHT } from '../object-view/ports-overview/models/ports-overview.types';
import { RenderResult } from '../../models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Outlets the section slot only, which is all the copy page hands the render kernel. */
@Component({
    selector: 'cmdb-render',
    template: `@if (sectionSlotIndex != null) { <ng-container [ngTemplateOutlet]="sectionSlot" /> }`,
    imports: [NgTemplateOutlet]
})
class RenderStubComponent {
    @Input() typeInstance: unknown;
    @Input() renderResult: unknown;
    @Input() mode: unknown;
    @Input() renderForm: unknown;
    @Input() sectionSlot: TemplateRef<unknown> | null = null;
    @Input() sectionSlotIndex: number | null = null;
}


describe('ObjectCopyComponent', () => {
    const SOURCE_ID = 98312;

    let fixture: ComponentFixture<ObjectCopyComponent>;
    let objectService: jasmine.SpyObj<ObjectService>;
    let access$: BehaviorSubject<PortsAccess>;
    let rights: string[];

    const renderResult = (usesPorts: boolean): RenderResult => ({
        object_information: { object_id: SOURCE_ID },
        type_information: { type_id: 5, active: true, uses_ports: usesPorts, port_section_index: 0 },
        fields: []
    } as unknown as RenderResult);

    const checkbox = (): HTMLInputElement | null =>
        fixture.nativeElement.querySelector('#object-copy-clone-ports');

    const render = (usesPorts = true): void => {
        objectService.getObject.and.returnValue(of(renderResult(usesPorts)));
        fixture = TestBed.createComponent(ObjectCopyComponent);
        fixture.detectChanges();
    };

    beforeEach(() => {
        rights = [PORT_ADD_RIGHT];
        access$ = new BehaviorSubject<PortsAccess>(PortsAccess.FULL);
        objectService = jasmine.createSpyObj<ObjectService>('ObjectService', ['getObject', 'postObject']);
        objectService.postObject.and.returnValue(of(77));

        TestBed.configureTestingModule({
            declarations: [ObjectCopyComponent, CheckboxComponent, PermissionLinkDirective],
            imports: [ReactiveFormsModule, RenderStubComponent],
            schemas: [NO_ERRORS_SCHEMA],
            providers: [
                { provide: ObjectService, useValue: objectService },
                { provide: TypeService, useValue: { getType: () => of({}) } },
                { provide: ActivatedRoute, useValue: { params: of({ publicID: String(SOURCE_ID) }) } },
                { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
                { provide: UserService, useValue: { getCurrentUser: () => ({ public_id: 1 }) } },
                { provide: SidebarService, useValue: jasmine.createSpyObj('SidebarService', ['updateTypeCounter']) },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['success', 'error']) },
                { provide: LocationService, useValue: { locationTreeName: '' } },
                { provide: PortsLicenseService, useValue: { access$: () => access$ } },
                {
                    provide: PermissionService,
                    useValue: { hasRight: (right: string) => rights.includes(right), hasExtendedRight: () => false }
                },
                { provide: AclPermissionService, useValue: {} }
            ]
        });
    });

    it('offers to copy the ports of a ports type', () => {
        render();

        expect(checkbox()).not.toBeNull();
        expect(checkbox()?.checked).toBeFalse();
    });


    it('offers nothing for a type without ports', () => {
        render(false);

        expect(checkbox()).toBeNull();
    });


    it('offers nothing without the right to add ports', () => {
        rights = [];
        render();

        expect(checkbox()).toBeNull();
    });


    it('offers nothing once the license no longer allows adding ports', () => {
        access$.next(PortsAccess.LAPSED);
        render();

        expect(checkbox()).toBeNull();
    });


    it('copies without the ports unless asked to', () => {
        render();

        fixture.componentInstance.copyObject();

        expect(objectService.postObject).toHaveBeenCalledWith(jasmine.anything(), undefined);
    });


    it('names the source object when the ports are to be copied', () => {
        render();

        checkbox()!.click();
        fixture.componentInstance.copyObject();

        expect(objectService.postObject).toHaveBeenCalledWith(jasmine.anything(), SOURCE_ID);
    });
});
