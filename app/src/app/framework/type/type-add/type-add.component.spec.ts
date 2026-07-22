import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';

import { TypeAddComponent } from './type-add.component';
import { TypeService } from '../../services/type.service';
import { UserService } from '../../../management/services/user.service';
import { CmdbType } from '../../models/cmdb-type';

/**
 * Builds a copy-source type with one user-defined section (eligible for a new id)
 * and one global section (must keep its id).
 */
function buildCopySource(overrides: Record<string, unknown> = {}): CmdbType {
    return {
        public_id: 3,
        _id: 'mongo-id',
        author_id: 99,
        name: 'server',
        label: 'Server',
        active: true,
        fields: [{ name: 'field_old', type: 'text' }],
        render_meta: {
            icon: 'fa fa-cube',
            sections: [
                { type: 'section', name: 'section-old', label: 'Details', fields: ['field_old'] },
                { type: 'section', name: 'dg-location', label: 'Location', fields: [] }
            ],
            externals: [],
            summary: { fields: [] }
        },
        ...overrides
    } as unknown as CmdbType;
}

describe('TypeAddComponent (create / copy entry point)', () => {
    let fixture: ComponentFixture<TypeAddComponent>;
    let component: TypeAddComponent;
    let typeService: jasmine.SpyObj<TypeService>;

    async function setup(query: Record<string, unknown>, copyType?: CmdbType): Promise<void> {
        typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getType']);
        if (copyType) {
            typeService.getType.and.returnValue(of(copyType));
        }

        const userService = { getCurrentUser: () => ({ public_id: 7 }) } as unknown as UserService;
        const route = { queryParams: of(query) } as unknown as ActivatedRoute;

        await TestBed.configureTestingModule({
            declarations: [TypeAddComponent],
            providers: [
                { provide: ActivatedRoute, useValue: route },
                { provide: TypeService, useValue: typeService },
                { provide: UserService, useValue: userService }
            ]
        })
            .overrideComponent(TypeAddComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypeAddComponent);
        component = fixture.componentInstance;
    }

    describe('fresh type creation (no copy query param)', () => {
        it('starts with an empty type instance and does not fetch anything', async () => {
            await setup({});
            expect(component.typeInstance).toBeTruthy();
            expect(typeService.getType).not.toHaveBeenCalled();
        });
    });

    describe('copying an existing type', () => {
        it('strips identity fields, regenerates ids and reassigns ownership', async () => {
            await setup({ copy: '3' }, buildCopySource());

            expect(typeService.getType).toHaveBeenCalledWith('3' as any);
            expect((component.typeInstance as unknown as { public_id?: number }).public_id).toBeUndefined();
            expect((component.typeInstance as unknown as { _id?: string })._id).toBeUndefined();
            expect(component.typeInstance.author_id).toBe(7);
        });

        it('gives user-defined sections/fields new ids but leaves global sections untouched', async () => {
            await setup({ copy: '3' }, buildCopySource());

            const sections = component.typeInstance.render_meta.sections;
            const userSection = sections[0];
            const globalSection = sections[1];

            expect(userSection.name).not.toBe('section-old');
            expect(userSection.name.startsWith('section-')).toBeTrue();
            expect(globalSection.name).toBe('dg-location');

            const renamedField = component.typeInstance.fields[0];
            expect(renamedField.name.startsWith('text-')).toBeTrue();
            expect(userSection.fields[0]).toBe(renamedField.name);
        });
    });

    describe('id helpers', () => {
        beforeEach(async () => {
            await setup({});
        });

        it('isGlobalSection recognizes dg- and dg_gst- prefixes only', () => {
            const isGlobal = (name: string) => (component as any).isGlobalSection(name);
            expect(isGlobal('dg-location')).toBeTrue();
            expect(isGlobal('dg_gst-1234')).toBeTrue();
            expect(isGlobal('section-1234')).toBeFalse();
            expect(isGlobal('text-1234')).toBeFalse();
        });

        it('generateNewID keeps the dg_location id fixed', () => {
            expect((component as any).generateNewID('location')).toBe('dg_location');
        });

        it('generateNewID normalizes section / section_template prefixes and appends a uuid', () => {
            const generate = (name: string) => (component as any).generateNewID(name) as string;
            expect(generate('section-old').startsWith('section-')).toBeTrue();
            expect(generate('section_template-abc').startsWith('section_template-')).toBeTrue();
            expect(generate('text')).toMatch(/^text-[0-9a-f-]+$/);
        });
    });
});
