import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TypeAclStepComponent } from './type-acl-step.component';
import { CmdbType } from '../../../models/cmdb-type';
import { AccessControlList } from 'src/app/modules/acl/acl.types';

function buildType(activated: boolean): CmdbType {
    return {
        public_id: 1,
        name: 'server',
        label: 'Server',
        active: true,
        fields: [],
        acl: new AccessControlList(activated, { includes: {} }),
        render_meta: {
            icon: 'fa fa-cube',
            sections: [],
            externals: [],
            summary: { fields: [] }
        }
    } as CmdbType;
}

describe('TypeAclStepComponent (type creation - access control step)', () => {
    let component: TypeAclStepComponent;
    let fixture: ComponentFixture<TypeAclStepComponent>;

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [TypeAclStepComponent]
        })
            .overrideComponent(TypeAclStepComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypeAclStepComponent);
        component = fixture.componentInstance;
    });

    describe('initialization from the type instance', () => {
        it('patches the form from an existing ACL configuration', () => {
            component.TypeInstance = buildType(true);
            expect(component.activatedStatus).toBeTrue();
        });
    });

    describe('validity emission', () => {
        beforeEach(() => {
            component.TypeInstance = buildType(false);
            component.ngOnInit();
        });

        it('reports the step as valid and empty while ACL is deactivated', () => {
            const isEmptySpy = spyOn(component.isEmpty, 'emit');
            const validSpy = spyOn(component.validateChange, 'emit');

            component.form.get('activated').setValue(false);

            expect(isEmptySpy).toHaveBeenCalledWith(true);
            expect(validSpy).toHaveBeenCalledWith(true);
        });

        it('reports validity based on the form once ACL is activated', () => {
            const validSpy = spyOn(component.validateChange, 'emit');

            component.form.get('activated').setValue(true);

            expect(validSpy).toHaveBeenCalledWith(true);
        });

        it('mirrors the form value into the type instance ACL', () => {
            component.form.get('activated').setValue(true);
            expect(component.typeInstance.acl.activated).toBeTrue();
        });
    });

    describe('onAddChange() empty-state tracking', () => {
        beforeEach(() => {
            component.TypeInstance = buildType(true);
            component.ngOnInit();
        });

        it('treats no groups and no permissions as empty', () => {
            const isEmptySpy = spyOn(component.isEmpty, 'emit');
            component.onAddChange([[], false]);
            expect(isEmptySpy).toHaveBeenCalledWith(true);
        });

        it('treats a selected group as not empty', () => {
            const isEmptySpy = spyOn(component.isEmpty, 'emit');
            component.onAddChange([['group-1'], false]);
            expect(isEmptySpy).toHaveBeenCalledWith(false);
        });

        it('treats a selected permission as not empty', () => {
            const isEmptySpy = spyOn(component.isEmpty, 'emit');
            component.onAddChange([[], true]);
            expect(isEmptySpy).toHaveBeenCalledWith(false);
        });
    });
});
