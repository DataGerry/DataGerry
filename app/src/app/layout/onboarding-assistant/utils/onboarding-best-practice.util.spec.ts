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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/


import { BestPracticeModelCard, BestPracticeSelectionPreview } from '../models/onboarding-best-practice.model';
import { matchesModelSearch, toModelSelectionLabel, toSelectionProblems } from './onboarding-best-practice.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const CARD: BestPracticeModelCard = {
    model_id: 'it_infrastructure',
    title: 'IT Infrastructure',
    badge: 'Complete CMDB',
    summary: 'Every asset class in one connected model.',
    counts: { categories: 2, types: 3, fields: 4, relations: 1 },
    category_labels: ['Hardware', 'Network'],
    required_features: [],
    missing_features: [],
    applicable: true
};

describe('matchesModelSearch', () => {
    it('matches every card for a blank term', () => {
        expect(matchesModelSearch(CARD, '')).toBeTrue();
        expect(matchesModelSearch(CARD, '   ')).toBeTrue();
    });

    it('matches the title, badge, summary and category labels regardless of case', () => {
        expect(matchesModelSearch(CARD, 'infra')).toBeTrue();
        expect(matchesModelSearch(CARD, 'cmdb')).toBeTrue();
        expect(matchesModelSearch(CARD, 'CONNECTED')).toBeTrue();
        expect(matchesModelSearch(CARD, 'network')).toBeTrue();
    });

    it('ignores surrounding whitespace', () => {
        expect(matchesModelSearch(CARD, '  hardware ')).toBeTrue();
    });

    it('rejects a term no field holds', () => {
        expect(matchesModelSearch(CARD, 'kubernetes')).toBeFalse();
    });
});


describe('toModelSelectionLabel', () => {
    const titled = (title: string): BestPracticeModelCard => ({ ...CARD, title });

    it('names one, two and more models', () => {
        expect(toModelSelectionLabel([titled('Contacts')])).toBe('Contacts model');
        expect(toModelSelectionLabel([titled('Contacts'), titled('Network')])).toBe('Contacts and Network models');
        expect(toModelSelectionLabel([titled('A'), titled('B'), titled('C')])).toBe('A, B and C models');
    });
});


describe('toSelectionProblems', () => {
    const PREVIEW: BestPracticeSelectionPreview = {
        model_ids: ['contacts', 'it_infrastructure'],
        counts: { categories: 5, types: 18, fields: 155, relations: 6 },
        category_labels: [],
        required_features: [],
        missing_features: [],
        conflicts: [],
        merged: {},
        problems: [],
        reset_blockers: [],
        applicable: true
    };

    it('finds nothing for an applicable selection', () => {
        expect(toSelectionProblems(PREVIEW)).toEqual([]);
    });

    it('lists conflicts, import problems and reset blockers in that order', () => {
        const problems = toSelectionProblems({
            ...PREVIEW,
            conflicts: ['conflict'],
            problems: ['problem'],
            reset_blockers: ['blocker'],
            applicable: false
        });

        expect(problems).toEqual(['conflict', 'problem', 'blocker']);
    });

    it('explains a refusal that names no reason', () => {
        expect(toSelectionProblems({ ...PREVIEW, applicable: false })).toEqual(['The selected models cannot be applied.']);
    });
});
