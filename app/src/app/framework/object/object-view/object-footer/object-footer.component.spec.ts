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
import { NO_ERRORS_SCHEMA, SimpleChange, SimpleChanges } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { RenderResult } from '../../../models/cmdb-render';
import { SpecialType } from '../../../models/special-type';
import { ObjectFooterComponent } from './object-footer.component';

/* ------------------------------------------------------------------------------------------------------------------ */

const RACK_ID = 42;
const MOUNTED_ID = 43;

const objectOf = (objectId: number, specialType?: SpecialType): RenderResult => ({
    object_information: { object_id: objectId, special_type: specialType },
    type_information: { type_id: 1 }
} as RenderResult);

/* ------------------------------------------------------------------------------------------------------------------ */

describe('ObjectFooterComponent', () => {
    let component: ObjectFooterComponent;

    /** Hands the component an object the way Angular does: the input setter, then the lifecycle hook. */
    const show = (renderResult: RenderResult) => {
        const previousValue = component.renderResult;
        component.renderResult = renderResult;

        const changes: SimpleChanges = {
            renderResult: new SimpleChange(previousValue, renderResult, previousValue === undefined)
        };

        component.ngOnChanges(changes);
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [ObjectFooterComponent],
            providers: [
                { provide: PremiumFeatureService, useValue: { isAvailable: () => true, isAvailable$: () => null } },
                { provide: PermissionService, useValue: { hasRight: () => true, hasExtendedRight: () => true } }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        component = TestBed.createComponent(ObjectFooterComponent).componentInstance;
    });

    it('leads a rack object with its drawing', () => {
        show(objectOf(RACK_ID, SpecialType.RACK));

        expect(component.activeTab).toBe('rack-view');
        expect(component.rackTabVisited).toBeTrue();
    });

    it('keeps the drawing when the same object is handed over again after a write', () => {
        show(objectOf(RACK_ID, SpecialType.RACK));

        show(objectOf(RACK_ID, SpecialType.RACK));

        expect(component.activeTab).toBe('rack-view');
        expect(component.rackTabVisited).toBeTrue();
    });

    it('keeps the drawing built when the re-read lands while another tab is open', () => {
        show(objectOf(RACK_ID, SpecialType.RACK));
        component.selectTab('logs');

        show(objectOf(RACK_ID, SpecialType.RACK));

        expect(component.activeTab).toBe('logs');
        expect(component.rackTabVisited).toBeTrue();
    });

    it('drops the drawing when another object is shown', () => {
        show(objectOf(RACK_ID, SpecialType.RACK));

        show(objectOf(MOUNTED_ID));

        expect(component.activeTab).toBe('risk-assessments');
        expect(component.rackTabVisited).toBeFalse();
    });
});
