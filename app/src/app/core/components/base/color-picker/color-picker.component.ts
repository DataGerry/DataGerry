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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, ElementRef, Input, ViewChild, forwardRef } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { NgbDropdown } from '@ng-bootstrap/ng-bootstrap';

import { Hsl, hexToHsl, hslToHex } from '../../../utils/color-utils';

/** A colour is only painted/committed when it is a plain CSS name or a hex literal. */
const SAFE_COLOR = /^(#(?:[0-9a-f]{3}|[0-9a-f]{6})|[a-z]{3,20})$/i;

/** A small, fixed palette - enough to pick a common cable/port colour without touching the sliders. */
const DEFAULT_PRESETS: readonly string[] = [
    '#e94d18', '#f4511e', '#fb8c00', '#fdd835', '#7cb342', '#43a047',
    '#00897b', '#1e88e5', '#3949ab', '#8e24aa', '#d81b60', '#6d4c41',
    '#546e7a', '#000000', '#ffffff'
];

let uniqueColorPickerId = 0;

/**
 * Reusable colour field: free-text name/hex entry plus a swatch that opens a preset palette and
 * three HSL sliders. Everything happens inside the popover - a native `input[type=color]` would
 * hand the job to a browser dialog no page can dismiss, which Firefox leaves standing on screen.
 */
@Component({
    selector: 'app-color-picker',
    templateUrl: './color-picker.component.html',
    styleUrls: ['./color-picker.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => ColorPickerComponent),
            multi: true
        }
    ],
    standalone: false
})
export class ColorPickerComponent implements ControlValueAccessor {
    @Input() label = 'Color';
    @Input() placeholder = 'e.g. blue or #1e88e5';
    @Input() required = false;
    @Input() disabled = false;
    @Input() errorMessage = '';
    @Input() presets: readonly string[] = DEFAULT_PRESETS;

    @ViewChild('swatchToggle') private swatchToggle?: ElementRef<HTMLButtonElement>;
    @ViewChild('hueSlider') private hueSlider?: ElementRef<HTMLInputElement>;

    public readonly controlId = `app-color-picker-${ ++uniqueColorPickerId }`;
    public value = '';
    public custom: Hsl = hexToHsl(null);

    private onChange: (value: string) => void = () => {};
    private onTouched: () => void = () => {};

/* -------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    /** Only painted once the typed text is something a browser can actually render. */
    public get swatchColor(): string | null {
        const trimmed = this.value.trim();

        return SAFE_COLOR.test(trimmed) ? trimmed : null;
    }

    /** What the sliders currently describe - shown next to them, not written until one is moved. */
    public get customColor(): string {
        return hslToHex(this.custom);
    }

    public get saturationTrack(): string {
        return `linear-gradient(to right, hsl(${ this.custom.hue }, 0%, ${ this.custom.lightness }%),`
            + ` hsl(${ this.custom.hue }, 100%, ${ this.custom.lightness }%))`;
    }

    public get lightnessTrack(): string {
        return `linear-gradient(to right, #000,`
            + ` hsl(${ this.custom.hue }, ${ this.custom.saturation }%, 50%), #fff)`;
    }

/* --------------------------------------------- CONTROL VALUE ACCESSOR ---------------------------------------------- */

    public writeValue(value: string | null): void {
        this.value = value ?? '';
    }

    public registerOnChange(fn: (value: string) => void): void {
        this.onChange = fn;
    }

    public registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    public setDisabledState(isDisabled: boolean): void {
        this.disabled = isDisabled;
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------- */

    public onTextInput(event: Event): void {
        this.setValue((event.target as HTMLInputElement).value);
    }

    public onBlur(): void {
        this.onTouched();
    }

    /** A preset is a direct commit: set it and close the popover immediately. */
    public onPickPreset(preset: string, dropdown: NgbDropdown): void {
        this.setValue(preset);
        this.onTouched();
        this.closePopover(dropdown);
    }

    /**
     * The sliders start from whatever the field holds, so opening the palette never loses a colour.
     * The popover renders on the body, past every other control in the tab order, so it has to take
     * focus to be reachable at all - and hand it back when it closes with focus still inside it.
     */
    public onPopoverToggle(open: boolean): void {
        if (!open) {
            if (this.focusIsInPopover()) {
                this.swatchToggle?.nativeElement.focus();
            }

            return;
        }

        this.custom = hexToHsl(this.value);
        /* The menu is still display:none until the open class lands. */
        setTimeout(() => this.hueSlider?.nativeElement.focus());
    }

    /** Sliders write straight through - an untouched slider leaves the stored hex untouched too. */
    public onCustomChannel(channel: keyof Hsl, event: Event): void {
        const next: Hsl = { ...this.custom };

        next[channel] = Number((event.target as HTMLInputElement).value);
        this.custom = next;
        this.setValue(hslToHex(next));
    }

    /** The sliders have no "picked" moment of their own, so this is how a custom colour is finished. */
    public onUseCustom(dropdown: NgbDropdown): void {
        this.onTouched();
        this.closePopover(dropdown);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ------------------------------------------------ */

    /** True while focus sits on the popover's own markup, or was dropped when it was hidden. */
    private focusIsInPopover(): boolean {
        const active = document.activeElement;

        return !active || active === document.body || !!active.closest('.color-picker__menu');
    }

    /** Focus would be stranded on a hidden element otherwise. */
    private closePopover(dropdown: NgbDropdown): void {
        dropdown.close();
        this.swatchToggle?.nativeElement.focus();
    }

    private setValue(value: string): void {
        this.value = value;
        this.onChange(value);
    }
}
