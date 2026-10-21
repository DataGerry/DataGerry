import { ComponentFixture, TestBed } from "@angular/core/testing";
import { ChangeDetectorRef, NO_ERRORS_SCHEMA } from "@angular/core";
import { provideHttpClient, withInterceptorsFromDi } from "@angular/common/http";
import { provideHttpClientTesting } from "@angular/common/http/testing";

import { BuilderCanvasComponent } from "./builder-canvas.component";
import { CmdbTypeSchemaAdapter } from "../schema/cmdb-type-schema.adapter";


describe('Builder Canvas Component', () => {
    let component: BuilderCanvasComponent;
    let fixture: ComponentFixture<BuilderCanvasComponent>;


    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [BuilderCanvasComponent],
            providers: [
                ChangeDetectorRef,
                provideHttpClient(withInterceptorsFromDi()),
                provideHttpClientTesting()
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(BuilderCanvasComponent);
        component = fixture.componentInstance;
        fixture.detectChanges()
    });


    describe('update Section Color', () => {

        it('should update the bg_color of the section and reflect the change in the model', () => {

            component.mode = component.MODES.Edit;

            // Set up the edited type with a section, ensure bg_color is initialized
            const typeInstance = {
                render_meta: {
                    sections: [
                        {
                            type: 'section',
                            name: 'section-1',
                            label: 'Section 1',
                            fields: [],
                        }
                    ]
                },
                fields: []
            } as any;

            component.Schema = new CmdbTypeSchemaAdapter(typeInstance);

            const section = typeInstance.render_meta.sections[0];
            const newColor = '#ff5733';

            // Call the method to update the color
            component.updateSectionColor(section, newColor);

            // Verify that the color has been updated
            expect(section.bg_color).toBe(newColor);
            expect(typeInstance.render_meta.sections[0].bg_color).toBe(newColor);
        });

    })

})
