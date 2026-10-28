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


import { BestPracticeModelCard } from '../models/onboarding-best-practice.model';
import { matchesModelSearch } from './onboarding-best-practice.util';
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
