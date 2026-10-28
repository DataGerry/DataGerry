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

import { LICENSE_FEATURE_LABELS, LicenseFeature } from '../../../settings/license-management/models/license.model';
import {
    BestPracticeCountItem,
    BestPracticeModelCard,
    BestPracticeModelCardView,
    BestPracticeModelCounts,
    BestPracticeModelDetails,
    BestPracticeTypeGroup,
    BestPracticeTypeRef
} from '../models/onboarding-best-practice.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const COUNT_LABELS: Record<keyof BestPracticeModelCounts, [string, string]> = {
    categories: ['category', 'categories'],
    types: ['type', 'types'],
    fields: ['field', 'fields'],
    relations: ['relation', 'relations']
};


export function toCountItems(counts: BestPracticeModelCounts): BestPracticeCountItem[] {
    return (Object.keys(COUNT_LABELS) as (keyof BestPracticeModelCounts)[]).map(id => {
        const [singular, plural] = COUNT_LABELS[id];
        const value = counts[id] ?? 0;

        return { id, value, label: value === 1 ? singular : plural };
    });
}


/** Unknown feature keys fall back to the raw key. */
export function toFeatureList(features: LicenseFeature[]): string {
    return features.map(feature => LICENSE_FEATURE_LABELS[feature] ?? feature).join(', ');
}


export function toTypeLabelList(types: BestPracticeTypeRef[]): string {
    return types.map(type => type.label).join(', ');
}


export function toModelCardView(card: BestPracticeModelCard): BestPracticeModelCardView {
    return {
        ...card,
        countItems: toCountItems(card.counts),
        missingFeatureLabels: toFeatureList(card.missing_features)
    };
}


/** Case-insensitive match on title, badge, summary and category labels; a blank term matches every card. */
export function matchesModelSearch(card: BestPracticeModelCard, term: string): boolean {
    const query = term.trim().toLowerCase();

    if (!query) {
        return true;
    }

    return [card.title, card.badge, card.summary, ...card.category_labels]
        .some(text => text?.toLowerCase().includes(query));
}


/** The categories in model order, then the types no category holds. */
export function toTypeGroups(details: BestPracticeModelDetails): BestPracticeTypeGroup[] {
    const categoryLabels = new Map(details.categories.map(category => [category.name, category.label]));

    const groups: BestPracticeTypeGroup[] = details.categories.map(category => ({
        id: `category-${category.name}`,
        label: category.label,
        parentLabel: category.parent ? categoryLabels.get(category.parent) ?? category.parent : '',
        description: category.description,
        types: category.types
    }));

    if (details.uncategorized.length) {
        groups.push({
            id: 'uncategorized',
            label: 'Without category',
            parentLabel: '',
            description: null,
            types: details.uncategorized
        });
    }

    return groups;
}
