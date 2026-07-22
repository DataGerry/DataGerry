import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { TypeFieldsStepComponent } from './type-fields-step.component';
import { SectionTemplateService } from 'src/app/framework/section_templates/services/section-template.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SpecialTypeService } from '../../../services/special-type.service';
import { SpecialTypeSchemaMapper } from '../utils/special-type-schema.mapper';
import { CmdbType } from '../../../models/cmdb-type';
import { SpecialType } from '../../../models/special-type';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return {
        public_id: 1,
        name: 'server',
        label: 'Server',
        active: true,
        fields: [],
        render_meta: {
            icon: 'fa fa-cube',
            sections: [],
            externals: [],
            summary: { fields: [] }
        },
        ...overrides
    } as CmdbType;
}

describe('TypeFieldsStepComponent (type creation - content step)', () => {
    let component: TypeFieldsStepComponent;
    let fixture: ComponentFixture<TypeFieldsStepComponent>;

    let sectionTemplateService: jasmine.SpyObj<SectionTemplateService>;
    let toastService: jasmine.SpyObj<ToastService>;
    let specialTypeService: jasmine.SpyObj<SpecialTypeService>;

    beforeEach(async () => {
        sectionTemplateService = jasmine.createSpyObj<SectionTemplateService>('SectionTemplateService', ['getSectionTemplates']);
        sectionTemplateService.getSectionTemplates.and.returnValue(of({ results: [], total: 0, count: 0 } as any));

        toastService = jasmine.createSpyObj<ToastService>('ToastService', ['error']);

        specialTypeService = jasmine.createSpyObj<SpecialTypeService>('SpecialTypeService', ['getCachedSchema', 'getSchema']);
        specialTypeService.getCachedSchema.and.returnValue(null);

        await TestBed.configureTestingModule({
            declarations: [TypeFieldsStepComponent],
            providers: [
                { provide: SectionTemplateService, useValue: sectionTemplateService },
                { provide: ToastService, useValue: toastService },
                { provide: SpecialTypeService, useValue: specialTypeService }
            ]
        })
            .overrideComponent(TypeFieldsStepComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypeFieldsStepComponent);
        component = fixture.componentInstance;
    });

    describe('status getter (structure validity)', () => {
        it('is valid only when there is at least one field, one section, and the builder is valid', () => {
            component.typeInstance = buildType({
                fields: [{ name: 'f1' }],
                render_meta: {
                    icon: 'fa fa-cube',
                    sections: [{ type: 'section', name: 's1', label: 'S1', fields: ['f1'] }],
                    externals: [],
                    summary: { fields: [] }
                }
            });
            component.builderValid = true;
            expect(component.status).toBeTrue();
        });

        it('is invalid when there are no fields', () => {
            component.typeInstance = buildType({
                fields: [],
                render_meta: {
                    icon: 'fa fa-cube',
                    sections: [{ type: 'section', name: 's1', label: 'S1', fields: [] }],
                    externals: [],
                    summary: { fields: [] }
                }
            });
            component.builderValid = true;
            expect(component.status).toBeFalse();
        });

        it('is invalid when there are no sections', () => {
            component.typeInstance = buildType({ fields: [{ name: 'f1' }] });
            component.builderValid = true;
            expect(component.status).toBeFalse();
        });

        it('is invalid when the embedded builder reports an invalid state', () => {
            component.typeInstance = buildType({
                fields: [{ name: 'f1' }],
                render_meta: {
                    icon: 'fa fa-cube',
                    sections: [{ type: 'section', name: 's1', label: 'S1', fields: ['f1'] }],
                    externals: [],
                    summary: { fields: [] }
                }
            });
            component.builderValid = false;
            expect(component.status).toBeFalse();
        });
    });

    describe('onBuilderValidChange()', () => {
        beforeEach(() => {
            component.typeInstance = buildType({
                fields: [{ name: 'f1' }],
                render_meta: {
                    icon: 'fa fa-cube',
                    sections: [{ type: 'section', name: 's1', label: 'S1', fields: ['f1'] }],
                    externals: [],
                    summary: { fields: [] }
                }
            });
        });

        it('propagates the builder state and re-emits overall validity', () => {
            const emitSpy = spyOn(component.validateChange, 'emit');

            component.onBuilderValidChange(true);
            expect(component.builderValid).toBeTrue();
            expect(component.valid).toBeTrue();
            expect(emitSpy).toHaveBeenCalledWith(true);

            component.onBuilderValidChange(false);
            expect(component.builderValid).toBeFalse();
            expect(component.valid).toBeFalse();
            expect(emitSpy).toHaveBeenCalledWith(false);
        });
    });

    describe('section template loading', () => {
        it('splits templates into global and non-global collections', () => {
            component.typeInstance = buildType();
            sectionTemplateService.getSectionTemplates.and.returnValue(of({
                results: [
                    { public_id: 1, name: 'local', is_global: false },
                    { public_id: 2, name: 'shared', is_global: true }
                ],
                total: 2,
                count: 2
            } as any));

            component.ngOnInit();

            expect(component.sectionTemplates.map((t) => t.name)).toEqual(['local']);
            expect(component.globalSectionTemplates.map((t) => t.name)).toEqual(['shared']);
        });

        it('surfaces an error toast if templates cannot be loaded', () => {
            component.typeInstance = buildType();
            sectionTemplateService.getSectionTemplates.and.returnValue(
                throwError(() => ({ error: { message: 'templates unavailable' } }))
            );

            component.ngOnInit();

            expect(toastService.error).toHaveBeenCalledWith('templates unavailable');
        });
    });

    describe('special type field locks', () => {
        it('locks section and field names from a cached IPAM schema', () => {
            spyOn(SpecialTypeSchemaMapper, 'validateSchema').and.returnValue({ valid: true } as any);
            specialTypeService.getCachedSchema.and.returnValue({
                special_type: SpecialType.SUBNET,
                sections: [{ type: 'section', name: 'ipam_sec', label: 'IPAM', fields: [] }],
                fields: [{ type: 'text', name: 'ipam_fld', label: 'IP' }]
            });

            component.typeInstance = buildType({ special_type: SpecialType.SUBNET });
            component.ngOnInit();

            expect(component.lockedSectionNames).toEqual(['ipam_sec']);
            expect(component.lockedFieldNames).toEqual(['ipam_fld']);
        });

        it('keeps locks empty for a regular (non-special) type', () => {
            component.typeInstance = buildType();
            component.ngOnInit();

            expect(component.lockedSectionNames).toEqual([]);
            expect(component.lockedFieldNames).toEqual([]);
            expect(specialTypeService.getCachedSchema).not.toHaveBeenCalled();
        });
    });
});
