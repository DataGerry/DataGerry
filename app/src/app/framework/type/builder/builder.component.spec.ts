import { ComponentFixture, fakeAsync, TestBed, tick } from "@angular/core/testing";
import { BuilderComponent } from "./builder.component"
import { ChangeDetectorRef, NO_ERRORS_SCHEMA } from "@angular/core";
import { provideHttpClient, withInterceptorsFromDi } from "@angular/common/http";
import { provideHttpClientTesting } from "@angular/common/http/testing";
import { LocationFieldDeletionService } from "../services/location-field-deletion.service";


describe('Builder Component', () => {
    let component: BuilderComponent;
    let fixture: ComponentFixture<BuilderComponent>;
    let changeDetector: ChangeDetectorRef;


    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [BuilderComponent],
            providers: [
                ChangeDetectorRef,
                { provide: LocationFieldDeletionService, useValue: {} },
                provideHttpClient(withInterceptorsFromDi()),
                provideHttpClientTesting()
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(BuilderComponent);
        component = fixture.componentInstance;
        changeDetector = TestBed.inject(ChangeDetectorRef);
        fixture.detectChanges()
    });


    describe('update Section Color', () => {

        it('should update the bg_color of the section and reflect the change in typeInstance', () => {

            component.mode = component.MODES.Edit;

            // Set up typeInstance with a section, ensure bg_color is initialized
            component.typeInstance = {
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

            const section = component.typeInstance.render_meta.sections[0];
            const newColor = '#ff5733';

            // Call the method to update the color
            component.updateSectionColor(section, newColor);

            // Verify that the color has been updated
            expect(section.bg_color).toBe(newColor);
            expect(component.typeInstance.render_meta.sections[0].bg_color).toBe(newColor);
        });

    })

})

