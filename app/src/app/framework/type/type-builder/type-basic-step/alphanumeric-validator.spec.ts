import { UntypedFormControl } from '@angular/forms';
import { ValidationErrors } from '@angular/forms';

import { alphanumericValidator } from './alphanumeric-validator';

/**
 * The type name is the technical identifier of a CMDB type. It must only contain
 * letters (including unicode letters/umlauts), numbers, hyphens and underscores.
 * These tests lock down exactly which inputs are accepted and rejected.
 */
describe('alphanumericValidator (type name character rules)', () => {

    const runValidator = (value: unknown): ValidationErrors | null => {
        return alphanumericValidator()(new UntypedFormControl(value));
    };

    describe('accepted values', () => {
        it('accepts an empty string (required is handled by a separate validator)', () => {
            expect(runValidator('')).toBeNull();
        });

        it('accepts plain lowercase letters', () => {
            expect(runValidator('server')).toBeNull();
        });

        it('accepts mixed case letters', () => {
            expect(runValidator('WebServer')).toBeNull();
        });

        it('accepts digits', () => {
            expect(runValidator('12345')).toBeNull();
        });

        it('accepts letters combined with digits', () => {
            expect(runValidator('router42')).toBeNull();
        });

        it('accepts underscores', () => {
            expect(runValidator('network_device')).toBeNull();
        });

        it('accepts hyphens', () => {
            expect(runValidator('network-device')).toBeNull();
        });

        it('accepts a combination of underscores, hyphens, letters and digits', () => {
            expect(runValidator('my_type-01')).toBeNull();
        });

        it('accepts unicode letters with umlauts', () => {
            expect(runValidator('Gebäude')).toBeNull();
        });

        it('accepts non-latin unicode letters', () => {
            expect(runValidator('日本語')).toBeNull();
        });
    });

    describe('rejected values', () => {
        const expectInvalid = (value: string) => {
            expect(runValidator(value)).toEqual({ invalidCharacters: true });
        };

        it('rejects whitespace between words', () => {
            expectInvalid('web server');
        });

        it('rejects a leading space', () => {
            expectInvalid(' server');
        });

        it('rejects dots', () => {
            expectInvalid('web.server');
        });

        it('rejects the @ character', () => {
            expectInvalid('admin@host');
        });

        it('rejects slashes', () => {
            expectInvalid('path/to/type');
        });

        it('rejects special characters like ! and #', () => {
            expectInvalid('type!');
            expectInvalid('type#1');
        });

        it('rejects parentheses and brackets', () => {
            expectInvalid('type(1)');
            expectInvalid('type[1]');
        });
    });
});
