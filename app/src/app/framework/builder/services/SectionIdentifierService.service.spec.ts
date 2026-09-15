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
import { firstValueFrom } from 'rxjs';

import { SectionIdentifierService } from './SectionIdentifierService.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('SectionIdentifierService', () => {

    let service: SectionIdentifierService;

    beforeEach(() => {
        service = new SectionIdentifierService();
    });


    it('drops the focused section along with the registry', async () => {
        // The registry is app-wide. A builder that kept its active index after being destroyed made
        // the next builder page rename a section this registry no longer knows.
        service.syncSections(['first', 'second']);
        service.setActiveIndex(1);

        service.resetIdentifiers();

        await expectAsync(firstValueFrom(service.getActiveIndex())).toBeResolvedTo(null);
    });


    it('only reports an index the registry actually holds', () => {
        service.syncSections(['first']);

        expect(service.hasSectionAtIndex(0)).toBeTrue();
        expect(service.hasSectionAtIndex(1)).toBeFalse();
        expect(service.hasSectionAtIndex(null)).toBeFalse();
        expect(service.hasSectionAtIndex(undefined)).toBeFalse();
    });
});
