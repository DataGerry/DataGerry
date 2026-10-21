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
import { ComponentFixture, TestBed, fakeAsync, tick, flush } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';

import { SectionFieldEditComponent } from './section-field-edit.component';
import { SectionIdentifierService } from 'src/app/framework/builder/services/SectionIdentifierService.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { CopyService } from 'src/app/core/services/copy.service';
import { CmdbMode } from 'src/app/framework/modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The editor against the REAL identifier registry, the way the type builder wires the two together:
 * the canvas registers every section by index and publishes the focused one, the editor renames it.
 * The spy-based specs cannot catch a disagreement between those two halves.
 */
describe('SectionFieldEditComponent against the real identifier registry', () => {

    let component: SectionFieldEditComponent;
    let fixture: ComponentFixture<SectionFieldEditComponent>;
    let registry: SectionIdentifierService;

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [SectionFieldEditComponent],
            imports: [ReactiveFormsModule],
            providers: [
                SectionIdentifierService,
                ValidationService,
                { provide: CopyService, useValue: jasmine.createSpyObj('CopyService', ['copyWithFeedback']) }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(SectionFieldEditComponent);
        component = fixture.componentInstance;
        registry = TestBed.inject(SectionIdentifierService);
    });


    /** Mounts the editor on one of the sections the canvas has registered, as a focused section. */
    function mountOn(sectionNames: Array<string>, focusedIndex: number, mode: CmdbMode = CmdbMode.Create) {
        registry.syncSections(sectionNames);
        registry.setActiveIndex(focusedIndex);

        const sections = sectionNames.map(name => ({ name, label: name, type: 'section' }));
        component.data = sections[focusedIndex];
        component.sections = sections;
        component.mode = mode;

        fixture.detectChanges();
    }


    function rename(newName: string) {
        component.nameControl.setValue(newName, { emitEvent: false });
        component.onInputChange(newName, 'name');
        tick(300);
        flush();
    }


    it('renames a registered section and tells the registry about it', fakeAsync(() => {
        mountOn(['sec_a', 'sec_b'], 1);

        rename('sec_c');

        expect(component.isIdentifierValid).toBeTrue();
        expect(registry.sectionExists('sec_c'))
            .withContext('the registry must follow the rename, or later duplicate checks go stale')
            .toBeTrue();
        expect(registry.sectionExists('sec_b')).toBeFalse();
    }));


    it('still rejects a rename onto a sibling identifier', fakeAsync(() => {
        mountOn(['sec_a', 'sec_b'], 1);

        rename('sec_a');

        expect(component.isIdentifierValid).toBeFalse();
        expect(component.nameControl.errors?.duplicateIdentifier).toBeTrue();
    }));


    it('renames the same section twice in a row', fakeAsync(() => {
        mountOn(['sec_a', 'sec_b'], 1);

        rename('sec_c');
        rename('sec_d');

        expect(component.isIdentifierValid).toBeTrue();
        expect(registry.sectionExists('sec_d')).toBeTrue();
        expect(registry.sectionExists('sec_c')).toBeFalse();
    }));


    it('renames a multi-data-section in a type, which syncs on every change', fakeAsync(() => {
        registry.syncSections(['mds_a', 'other']);
        registry.setActiveIndex(0);

        component.data = { name: 'mds_a', label: 'A', type: 'multi-data-section' };
        component.sections = [component.data, { name: 'other', type: 'section' }];
        component.mode = CmdbMode.Edit;
        fixture.detectChanges();

        rename('mds_renamed');

        expect(component.isIdentifierValid).toBeTrue();
        expect(registry.sectionExists('mds_renamed')).toBeTrue();
    }));


    it('leaves a focused index the registry has outgrown alone', fakeAsync(() => {
        // Removing sections shifts every later index down, but the published focus does not follow.
        mountOn(['sec_a', 'sec_b', 'sec_c'], 2);
        registry.removeSection(0);

        rename('sec_d');

        // Nothing to rename at that index any more - that is not a uniqueness failure.
        expect(component.isIdentifierValid).toBeTrue();
    }));


    it('survives a second builder session after the first one reset the registry', fakeAsync(() => {
        // Canvas #1 runs and is destroyed.
        registry.syncSections(['old_a', 'old_b']);
        registry.setActiveIndex(1);
        registry.resetIdentifiers();

        // Canvas #2 mounts and registers its own sections.
        mountOn(['new_a', 'new_b'], 1);

        rename('new_c');

        expect(component.isIdentifierValid).toBeTrue();
        expect(registry.sectionExists('new_c')).toBeTrue();
        expect(registry.sectionExists('old_b')).toBeFalse();
    }));


    it('does not flag an unregistered section - the section template page', fakeAsync(() => {
        // Canvas destroyed; the section template builder never registers its single fixed section.
        registry.syncSections(['some_type_section']);
        registry.setActiveIndex(0);
        registry.resetIdentifiers();

        component.data = {
            name: 'section_template-2fe3b0ef', label: 'clone ports', type: 'multi-data-section'
        };
        component.sections = [component.data];
        component.mode = CmdbMode.Edit;
        fixture.detectChanges();

        rename('section_template-other');

        expect(component.isIdentifierValid).toBeTrue();
        expect(component.nameControl.errors?.duplicateIdentifier).toBeFalsy();
    }));
});
