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

export const DOCAPI_SUPPORTED_CSS_PROPERTIES: readonly string[] = [
    'background-color',
    'border-bottom-color, border-bottom-style, border-bottom-width',
    'border-left-color, border-left-style, border-left-width',
    'border-right-color, border-right-style, border-right-width',
    'border-top-color, border-top-style, border-top-width',
    'color, display',
    'font-family, font-size, font-style, font-weight',
    'height',
    'line-height, list-style-type',
    'margin-bottom, margin-left, margin-right, margin-top',
    'padding-bottom, padding-left, padding-right, padding-top',
    'page-break-after, page-break-before',
    'size',
    'text-align, text-decoration, text-indent',
    'vertical-align',
    'white-space',
    'width',
    'zoom'
];

export const DOCAPI_UNSUPPORTED_CSS_PROPERTIES: readonly string[] = [
    'display: flex and flexbox properties',
    'CSS Grid',
    'position: fixed and position: absolute for normal web-style layout',
    'float',
    'z-index',
    'overflow',
    'max-width, min-width, max-height, min-height',
    'border-radius',
    'box-shadow',
    'text-shadow',
    'opacity',
    'transform',
    'transition',
    'animation',
    'filter',
    'object-fit',
    'media queries',
    'most CSS3 selectors and features'
];
