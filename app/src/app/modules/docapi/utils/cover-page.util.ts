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
import { DocTemplateCoverPage } from '../models/cmdb-doctemplate';

export const DEFAULT_COVER_PAGE: DocTemplateCoverPage = {
    activated: false,
    content: '',
    config: {}
};

export const normalizeCoverPage = (rawCoverPage: unknown): DocTemplateCoverPage => {
    if (!rawCoverPage || typeof rawCoverPage !== 'object') {
        return { ...DEFAULT_COVER_PAGE };
    }

    const coverPage = rawCoverPage as Partial<DocTemplateCoverPage>;
    const normalizedConfig = coverPage.config && typeof coverPage.config === 'object'
        ? coverPage.config
        : {};

    return {
        activated: typeof coverPage.activated === 'boolean' ? coverPage.activated : false,
        content: typeof coverPage.content === 'string' ? coverPage.content : '',
        config: normalizedConfig
    };
};
