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
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * What a request or response body is written in, as far as editing it is concerned.
 *
 * An invoker describes every body as the same tree of fields, whatever goes over the wire, and says
 * on the body which wire format that tree stands for: `format="xml"` for a SOAP service such as
 * Ivanti, `data="graphql"` for a GraphQL endpoint such as JDisc. The tree is the same; what a person
 * needs to see in it is not.
 */
export type BodyKind = 'json' | 'xml' | 'graphql';


/**
 * The node OpenCelium keeps an XML element's attributes in, namespaces among them.
 *
 * It sits beside the element's children in the tree, so to anything walking the tree it looks like
 * one more child - and an `xmlns` URL offered as a value to read or a field to fill is noise.
 */
export const XML_ATTRIBUTES = '__oc__attributes';


export function bodyKindOf(body: { data?: string; format?: string } | null | undefined): BodyKind {
    if (body?.data === 'graphql') {
        return 'graphql';
    }

    return body?.format === 'xml' ? 'xml' : 'json';
}


/** True for a path into an element's attributes rather than into its content. */
export function isXmlAttributePath(path: string): boolean {
    return path.split('.').some(segment => segment.replace(/\[[^\]]*\]$/, '') === XML_ATTRIBUTES);
}


/**
 * A path inside a SOAP message, from the operation's payload on.
 *
 * Every value of a SOAP call sits under the same `Envelope.Body.<Operation>` route, which pushes the
 * part that tells values apart off the right edge of any list. The route is cut at the element
 * after the Body - the operation's own element, which every value shares - whatever prefix the
 * namespace was given. A path that is not inside a Body is returned as it is.
 */
export function xmlPayloadPath(path: string): string {
    const segments = path.split('.');
    const body = segments.findIndex(segment => /(^|:)Body(\[[^\]]*\])?$/.test(segment));

    if (body === -1 || body + 2 > segments.length - 1) {
        return path;
    }

    return segments.slice(body + 2).join('.');
}


/**
 * The SOAP operation a message carries, read from the first element inside its Body.
 *
 * Empty when the tree is not a SOAP envelope - plain XML has no Body to look into.
 */
export function soapOperationOf(fields: unknown): string {
    const envelope = childEndingWith(fields, 'Envelope');
    const body = childEndingWith(envelope, 'Body');

    if (!body || typeof body !== 'object') {
        return '';
    }

    return Object.keys(body).find(key => key !== XML_ATTRIBUTES) ?? '';
}


/**
 * The route every value of a SOAP message shares - `soap:Envelope.soap:Body.ListMachines` - with
 * the prefixes the invoker uses. Empty when the tree is not a SOAP envelope.
 */
export function soapPayloadPrefix(fields: unknown): string {
    const envelope = keyEndingWith(fields, 'Envelope');
    const envelopeNode = envelope ? (fields as Record<string, unknown>)[envelope] : null;
    const body = keyEndingWith(envelopeNode, 'Body');
    const operation = soapOperationOf(fields);

    return envelope && body && operation ? `${envelope}.${body}.${operation}` : '';
}


/**
 * The tree written out as the XML it stands for, for reading rather than for sending.
 *
 * OpenCelium builds the real message; this only has to show a person what that message will look
 * like, with attributes in their place and a list as its repeated element.
 */
export function fieldsToXml(fields: unknown, indent = ''): string {
    if (!fields || typeof fields !== 'object' || Array.isArray(fields)) {
        return '';
    }

    return Object.entries(fields as Record<string, unknown>)
        .filter(([name]) => name !== XML_ATTRIBUTES)
        .flatMap(([name, value]) => (Array.isArray(value) ? value : [value])
            .map(item => elementXml(name, item, indent)))
        .join('\n');
}


function elementXml(name: string, value: unknown, indent: string): string {
    const attributes = value && typeof value === 'object' && !Array.isArray(value)
        ? attributesXml((value as Record<string, unknown>)[XML_ATTRIBUTES])
        : '';

    if (value && typeof value === 'object') {
        const inner = fieldsToXml(value, `${indent}  `);

        return inner
            ? `${indent}<${name}${attributes}>\n${inner}\n${indent}</${name}>`
            : `${indent}<${name}${attributes}/>`;
    }

    const text = value === null || value === undefined ? '' : String(value);

    return text
        ? `${indent}<${name}${attributes}>${escapeXml(text)}</${name}>`
        : `${indent}<${name}${attributes}/>`;
}


function attributesXml(attributes: unknown): string {
    if (!attributes || typeof attributes !== 'object') {
        return '';
    }

    return Object.entries(attributes as Record<string, unknown>)
        .map(([name, value]) => ` ${name}="${escapeXml(String(value ?? ''))}"`)
        .join('');
}


function escapeXml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


/** The child whose name ends in `local`, whatever namespace prefix it carries. */
function childEndingWith(node: unknown, local: string): unknown {
    const key = keyEndingWith(node, local);

    return key ? (node as Record<string, unknown>)[key] : null;
}


function keyEndingWith(node: unknown, local: string): string | null {
    if (!node || typeof node !== 'object' || Array.isArray(node)) {
        return null;
    }

    return Object.keys(node).find(candidate => candidate === local || candidate.endsWith(`:${local}`)) ?? null;
}
