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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TypeEditComponent } from './type-edit.component';
import { CmdbType } from '../../models/cmdb-type';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { CmdbMode } from '../../modes.enum';
import { TypeService } from '../../services/type.service';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { By } from '@angular/platform-browser';

describe('TypeEditComponent', () => {
    let component: TypeEditComponent;
    let fixture: ComponentFixture<TypeEditComponent>;

    const mockTypeInstance: CmdbType = {
        public_id: 1,
        label: 'Test Type',
        name: '',
        active: false,
        selectable_as_parent: false,
        author_id: 0,
        version: '',
        creation_time: undefined,
        editor_id: 0,
        last_edit_time: undefined,
        render_meta: undefined,
        fields: [],
        has_references: () => false,
        get_reference_fields: () => [],
    };

    const mockActivatedRoute = {
        queryParams: of({ stepIndex: 2 }),
        snapshot: {
            data: {
                type: mockTypeInstance,
            },
        },
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [TypeEditComponent],
            providers: [
                { provide: TypeService, useValue: {} },
                { provide: ActivatedRoute, useValue: mockActivatedRoute },
            ],
            schemas: [NO_ERRORS_SCHEMA],
        }).compileComponents();

        fixture = TestBed.createComponent(TypeEditComponent);
        component = fixture.componentInstance;
        fixture.detectChanges();  // Initial detection cycle
    });


    it('should create the component', () => {
        expect(component).toBeTruthy();
    });

    it('should set stepIndex from query params', () => {
        expect(component.stepIndex).toBe(2);
    });

    it('should initialize typeInstance from route data', () => {
        expect(component.typeInstance).toEqual(mockTypeInstance);
    });

    it('should set mode to Edit by default', () => {
        expect(component.mode).toBe(CmdbMode.Edit);
    });

    it('should render the content header with correct title', () => {
        const compiled = fixture.nativeElement;
        expect(compiled.querySelector('cmdb-content-header').getAttribute('title')).toContain(`Edit type ${mockTypeInstance.label}`);
    });

    it('should pass correct inputs to cmdb-type-builder component', () => {
        fixture.detectChanges();  // Trigger any remaining bindings
        const typeBuilderDebugElement = fixture.debugElement.query(By.css('cmdb-type-builder'));
        expect(typeBuilderDebugElement.componentInstance.stepIndex).toBe(2);
        expect(typeBuilderDebugElement.componentInstance.typeInstance).toEqual(mockTypeInstance);
        expect(typeBuilderDebugElement.componentInstance.mode).toBe(CmdbMode.Edit);
    });
});
