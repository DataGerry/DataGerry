import { UntypedFormControl, ValidationErrors, Validators } from '@angular/forms';

import { hexColorErrorMessage, hexColorValidator } from './hex-color-validator';

describe('hexColorValidator', () => {

    const runValidator = (value: unknown): ValidationErrors | null => {
        return hexColorValidator()(new UntypedFormControl(value));
    };

    it('accepts a six digit hex literal in either case', () => {
        expect(runValidator('#1e88e5')).toBeNull();
        expect(runValidator('#1E88E5')).toBeNull();
    });

    it('leaves an empty value to the required validator', () => {
        expect(runValidator('')).toBeNull();
        expect(runValidator(null)).toBeNull();
        expect(runValidator(undefined)).toBeNull();
    });

    it('refuses the short hex form the contrast and alpha helpers cannot parse', () => {
        expect(runValidator('#abc')).toEqual({ hexColor: true });
    });

    it('refuses a CSS colour name', () => {
        expect(runValidator('blue')).toEqual({ hexColor: true });
    });

    it('refuses a hex without its hash, with padding or half typed', () => {
        expect(runValidator('1e88e5')).toEqual({ hexColor: true });
        expect(runValidator(' #1e88e5 ')).toEqual({ hexColor: true });
        expect(runValidator('#1e88')).toEqual({ hexColor: true });
    });

    it('refuses a value that is not a string', () => {
        expect(runValidator(123456)).toEqual({ hexColor: true });
    });
});

describe('hexColorErrorMessage', () => {

    const touchedControl = (value: string, required = false): UntypedFormControl => {
        const control = new UntypedFormControl(value, required ? [Validators.required, hexColorValidator()] : hexColorValidator());

        control.markAsTouched();
        return control;
    };

    it('stays quiet until the field has been left', () => {
        expect(hexColorErrorMessage(new UntypedFormControl('blue', hexColorValidator()))).toBe('');
    });

    it('stays quiet for a valid colour', () => {
        expect(hexColorErrorMessage(touchedControl('#1e88e5'))).toBe('');
    });

    it('asks for a colour when a required one is missing', () => {
        expect(hexColorErrorMessage(touchedControl('', true))).toBe('Color is required.');
    });

    it('asks for the hex form when the value is not one', () => {
        expect(hexColorErrorMessage(touchedControl('blue'))).toBe('Enter a hex color such as #1e88e5.');
    });

    it('handles a missing control', () => {
        expect(hexColorErrorMessage(null)).toBe('');
    });
});
