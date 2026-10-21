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
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { NgbDropdown, NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';

import { ButtonComponent } from '../button/app-button.component';

import { ColorPickerComponent } from './color-picker.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('ColorPickerComponent (app-color-picker)', () => {
    let fixture: ComponentFixture<ColorPickerComponent>;
    let component: ColorPickerComponent;
    let dropdown: NgbDropdown;
    let committed: string[];

    /** The popover is rendered on the body, so its content is not under the component element. */
    const queryPopover = <T extends HTMLElement>(selector: string): T =>
        document.querySelector(selector) as T;

    const openPopover = (): void => {
        dropdown.open();
        fixture.detectChanges();
    };

    const slide = (channel: 'hue' | 'saturation' | 'lightness', amount: number): void => {
        const slider = queryPopover<HTMLInputElement>(`#${ component.controlId }-${ channel }`);

        slider.value = String(amount);
        slider.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [ColorPickerComponent, ButtonComponent],
            imports: [NgbDropdownModule]
        }).compileComponents();

        committed = [];
        fixture = TestBed.createComponent(ColorPickerComponent);
        component = fixture.componentInstance;
        component.registerOnChange((value: string) => committed.push(value));
        fixture.detectChanges();

        dropdown = fixture.debugElement.query(By.directive(NgbDropdown)).injector.get(NgbDropdown);
    });

    it('points its label at its own input', () => {
        const input = fixture.nativeElement.querySelector('.color-picker__input') as HTMLInputElement;
        const label = fixture.nativeElement.querySelector('label') as HTMLLabelElement;

        expect(input.id).toBe(component.controlId);
        expect(label.getAttribute('for')).toBe(input.id);
    });

    it('seeds the sliders from the colour the field already holds', () => {
        component.writeValue('#1e88e5');
        fixture.detectChanges();

        openPopover();

        expect(component.custom).toEqual({ hue: 208, saturation: 79, lightness: 51 });
    });

    it('leaves the stored colour untouched when no slider is moved', () => {
        component.writeValue('#1e88e5');
        fixture.detectChanges();

        openPopover();
        queryPopover<HTMLButtonElement>('.color-picker__custom app-button button').click();
        fixture.detectChanges();

        expect(component.value).toBe('#1e88e5');
        expect(committed).toEqual([]);
        expect(dropdown.isOpen()).toBeFalse();
    });

    it('writes a hex colour as the sliders move, without closing the popover', () => {
        openPopover();

        slide('hue', 208);
        slide('saturation', 79);
        slide('lightness', 51);

        expect(component.value).toBe('#1f89e5');
        expect(committed.length).toBe(3);
        expect(dropdown.isOpen()).toBeTrue();
    });

    it('closes the popover and takes focus back to the swatch on "Use this colour"', () => {
        openPopover();
        slide('hue', 120);

        const use = queryPopover<HTMLButtonElement>('.color-picker__custom app-button button');

        use.focus();
        use.click();
        fixture.detectChanges();

        expect(dropdown.isOpen()).toBeFalse();
        expect(document.activeElement).toBe(fixture.nativeElement.querySelector('.color-picker__swatch'));
    });

    it('closes the popover and takes focus back to the swatch when a preset is picked', () => {
        openPopover();

        (queryPopover<HTMLButtonElement>('.color-picker__preset')).click();
        fixture.detectChanges();

        expect(component.value).toBe(component.presets[0]);
        expect(dropdown.isOpen()).toBeFalse();
        expect(document.activeElement).toBe(fixture.nativeElement.querySelector('.color-picker__swatch'));
    });

    it('takes focus into the popover, which the body-hosted markup cannot get by tabbing', fakeAsync(() => {
        openPopover();
        tick();

        expect(document.activeElement).toBe(queryPopover(`#${ component.controlId }-hue`));
    }));

    it('hands focus back to the swatch when the popover closes with focus inside it', fakeAsync(() => {
        openPopover();
        tick();

        dropdown.close();
        fixture.detectChanges();

        expect(document.activeElement).toBe(fixture.nativeElement.querySelector('.color-picker__swatch'));
    }));

    it('leaves focus alone when the popover closes because the user went elsewhere', fakeAsync(() => {
        const elsewhere = fixture.nativeElement.querySelector('.color-picker__input') as HTMLInputElement;

        openPopover();
        tick();
        elsewhere.focus();

        dropdown.close();
        fixture.detectChanges();

        expect(document.activeElement).toBe(elsewhere);
    }));

    it('has no native colour dialog left to strand on screen', () => {
        openPopover();

        expect(document.querySelector('input[type="color"]')).toBeNull();
    });
});
