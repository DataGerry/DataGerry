import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SpecialTypeBadgeComponent } from './special-type-badge.component';
import { SpecialType } from '../../../framework/models/special-type';

describe('SpecialTypeBadgeComponent', () => {
    let component: SpecialTypeBadgeComponent;
    let fixture: ComponentFixture<SpecialTypeBadgeComponent>;

    const badge = (): HTMLElement | null =>
        fixture.nativeElement.querySelector('.special-type-badge');

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [SpecialTypeBadgeComponent]
        }).compileComponents();

        fixture = TestBed.createComponent(SpecialTypeBadgeComponent);
        component = fixture.componentInstance;
    });

    it('renders nothing for a regular type', () => {
        component.specialType = null;
        fixture.detectChanges();

        expect(badge()).toBeNull();
    });

    it('renders nothing for an empty token', () => {
        component.specialType = '';
        fixture.detectChanges();

        expect(badge()).toBeNull();
    });

    it('renders the token and a variant class per special type', () => {
        component.specialType = SpecialType.RACK;
        fixture.detectChanges();

        expect(badge().textContent.trim()).toBe('Rack');
        expect(badge().classList).toContain('special-type-badge--rack');
    });

    it('capitalizes only the first letter of the backend token', () => {
        component.specialType = SpecialType.SUPERNET;
        expect(component.displayToken).toBe('Supernet');

        component.specialType = 'vlan';
        expect(component.displayToken).toBe('Vlan');

        component.specialType = null;
        expect(component.displayToken).toBe('');
    });

    it('renders the token as text only, without an icon', () => {
        component.specialType = SpecialType.RACK;
        fixture.detectChanges();

        expect(badge().querySelector('i')).toBeNull();
    });

    it('marks the accent dot as decorative', () => {
        component.specialType = SpecialType.RACK;
        fixture.detectChanges();

        const dot = badge().querySelector('.special-type-badge__dot');

        expect(dot).not.toBeNull();
        expect(dot.getAttribute('aria-hidden')).toBe('true');
        expect(dot.textContent).toBe('');
    });

    it('gives every known special type its own variant class', () => {
        for (const specialType of Object.values(SpecialType)) {
            component.specialType = specialType;
            expect(component.badgeClass).toBe(`special-type-badge special-type-badge--${specialType.toLowerCase()}`);
        }
    });

    it('still builds a variant class for an unknown token', () => {
        component.specialType = 'FUTURE_TYPE';

        expect(component.badgeClass).toBe('special-type-badge special-type-badge--future_type');
    });

    it('strips characters a class name cannot carry from an unexpected token', () => {
        component.specialType = 'RACK" onmouseover="x';

        expect(component.badgeClass).toBe('special-type-badge special-type-badge--rackonmouseoverx');
    });

    it('exposes the backend description to assistive technology', () => {
        component.specialType = SpecialType.SUBNET;
        component.description = 'IPAM - Subnet class';
        fixture.detectChanges();

        expect(badge().querySelector('.visually-hidden').textContent).toContain('IPAM - Subnet class');
    });

    it('omits the description node when no description is provided', () => {
        component.specialType = SpecialType.SUBNET;
        fixture.detectChanges();

        expect(badge().querySelector('.visually-hidden')).toBeNull();
    });
});
