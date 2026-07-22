import { ComponentFixture, TestBed } from '@angular/core/testing';
import { UntypedFormControl } from '@angular/forms';

import { TypeMetaStepComponent } from './type-meta-step.component';
import { CmdbType } from '../../../models/cmdb-type';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return {
        public_id: 1,
        name: 'server',
        label: 'Server',
        active: true,
        fields: [],
        ci_explorer_label: '',
        render_meta: {
            icon: 'fa fa-cube',
            sections: [],
            externals: [],
            summary: { fields: [] }
        },
        ...overrides
    } as CmdbType;
}

describe('TypeMetaStepComponent (type creation - meta step)', () => {
    let component: TypeMetaStepComponent;
    let fixture: ComponentFixture<TypeMetaStepComponent>;

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [TypeMetaStepComponent]
        })
            .overrideComponent(TypeMetaStepComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypeMetaStepComponent);
        component = fixture.componentInstance;
    });

    describe('summary configuration', () => {
        beforeEach(() => {
            component.TypeInstance = buildType({ fields: [{ name: 'f1' }, { name: 'f2' }] });
        });

        it('requires both the summary fields and the CI explorer label', () => {
            component.summaryForm.reset();
            expect(component.summaryFields.hasError('required')).toBeTrue();
            expect(component.ciExplorerLabel.hasError('required')).toBeTrue();
        });

        it('onSummaryChange maps selected fields down to their names', () => {
            component.onSummaryChange([{ name: 'f1' }, { name: 'f2' }]);
            expect(component.typeInstance.render_meta.summary.fields).toEqual(['f1', 'f2']);
        });

        it('onCiExplorerChange stores the field name, or clears it when nothing is selected', () => {
            component.onCiExplorerChange({ name: 'f1' });
            expect(component.typeInstance.ci_explorer_label).toBe('f1');

            component.onCiExplorerChange(null);
            expect(component.typeInstance.ci_explorer_label).toBeNull();
        });
    });

    describe('external links', () => {
        beforeEach(() => {
            component.TypeInstance = buildType();
        });

        it('addExternal appends the form value and resets the form with a default icon', () => {
            component.externalsForm.patchValue({ name: 'wiki', label: 'Wiki', href: 'https://wiki/{}' });

            component.addExternal();

            expect(component.typeInstance.render_meta.externals.length).toBe(1);
            expect(component.typeInstance.render_meta.externals[0].name).toBe('wiki');
            expect(component.external_name.value).toBeNull();
            expect(component.externalsForm.get('icon').value).toBe('fas fa-external-link-alt');
        });

        it('deleteExternal removes the referenced link', () => {
            component.typeInstance.render_meta.externals = [
                { name: 'a', label: 'A', href: 'x', icon: '', fields: [] },
                { name: 'b', label: 'B', href: 'y', icon: '', fields: [] }
            ];
            const target = component.typeInstance.render_meta.externals[0];

            component.deleteExternal(target);

            expect(component.typeInstance.render_meta.externals.map((e) => e.name)).toEqual(['b']);
        });

        it('editExternal loads the link back into the form and removes the original entry', () => {
            component.typeInstance.render_meta.externals = [
                { name: 'wiki', label: 'Wiki', href: 'https://wiki', icon: 'fa fa-book', fields: [] }
            ];
            const target = component.typeInstance.render_meta.externals[0];

            component.editExternal(target);

            expect(component.typeInstance.render_meta.externals.length).toBe(0);
            expect(component.external_name.value).toBe('wiki');
            expect(component.external_label.value).toBe('Wiki');
        });

        it('listNameValidator rejects names already used by another external link', () => {
            component.typeInstance.render_meta.externals = [
                { name: 'wiki', label: 'Wiki', href: 'x', icon: '', fields: [] }
            ];
            const validate = component.listNameValidator();

            expect(validate(new UntypedFormControl('wiki'))).toEqual({ nameAlreadyTaken: { value: 'wiki' } });
            expect(validate(new UntypedFormControl('confluence'))).toBeNull();
        });

        it('auto-capitalizes the label from the name while typing', () => {
            component.ngOnInit();
            component.external_name.setValue('changelog');
            expect(component.external_label.value).toBe('Changelog');
        });

        it('detects placeholder tokens in the href', () => {
            component.ngOnInit();

            component.externalsForm.get('href').setValue('https://tool/{}');
            expect(component.hasInter).toBeTrue();

            component.externalsForm.get('href').setValue('https://tool/static');
            expect(component.hasInter).toBeFalse();
        });
    });

    describe('occurrences() helper', () => {
        it('counts the number of placeholder tokens', () => {
            expect(component.occurrences('a{}b{}c', '{}')).toBe(2);
            expect(component.occurrences('no tokens here', '{}')).toBe(0);
        });
    });

    describe('ngDoCheck field synchronization', () => {
        it('narrows the summary/CI-explorer field pool to fields actually placed in a section', () => {
            component.TypeInstance = buildType({
                fields: [{ name: 'a' }, { name: 'b' }],
                render_meta: {
                    icon: 'fa fa-cube',
                    sections: [{ type: 'section', name: 's1', label: 'S1', fields: ['a'] }],
                    externals: [],
                    summary: { fields: [] }
                }
            });

            component.ngDoCheck();

            expect(component.filteredFields.map((f: { name: string }) => f.name)).toEqual(['a']);
        });
    });
});
