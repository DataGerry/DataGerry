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
import {
    bodyKindOf,
    fieldsToXml,
    isXmlAttributePath,
    soapOperationOf,
    soapPayloadPrefix,
    xmlPayloadPath
} from './body-format.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Ivanti's ListMachines request, as OpenCelium hands the invoker's XML over. */
const IVANTI = {
    'soap:Envelope': {
        'soap:Header': '',
        '__oc__attributes': { 'xmlns:soap': 'http://schemas.xmlsoap.org/soap/envelope/' },
        'soap:Body': {
            ListMachines: {
                '__oc__attributes': { xmlns: 'http://landesk.com/MBSDKService/MBSDK/' },
                Filter: 'DeviceName = "a&b"'
            }
        }
    }
};


describe('body-format.model', () => {

    it('tells the three kinds of body apart', () => {
        expect(bodyKindOf({ data: 'graphql', format: 'json' })).toBe('graphql');
        expect(bodyKindOf({ data: 'raw', format: 'xml' })).toBe('xml');
        expect(bodyKindOf({ data: 'raw', format: 'json' })).toBe('json');
        expect(bodyKindOf(undefined)).toBe('json');
    });


    it('shows a SOAP path from the operation\'s content on', () => {
        expect(xmlPayloadPath('soap:Envelope.soap:Body.ListMachines.Filter')).toBe('Filter');
        expect(xmlPayloadPath('env:Envelope.env:Body.ListMachinesResponse.ListMachinesResult.Devices[i].Device.GUID'))
            .toBe('ListMachinesResult.Devices[i].Device.GUID');
        expect(xmlPayloadPath('soap:Envelope.soap:Body.ListMachines')).toBe('soap:Envelope.soap:Body.ListMachines');
        expect(xmlPayloadPath('params.title')).toBe('params.title');
    });


    it('recognises attributes wherever they sit', () => {
        expect(isXmlAttributePath('soap:Envelope.__oc__attributes.xmlns:soap')).toBeTrue();
        expect(isXmlAttributePath('soap:Envelope.soap:Body.ListMachines.Filter')).toBeFalse();
    });


    it('finds the SOAP operation and the route to its content', () => {
        expect(soapOperationOf(IVANTI)).toBe('ListMachines');
        expect(soapPayloadPrefix(IVANTI)).toBe('soap:Envelope.soap:Body.ListMachines');
        expect(soapPayloadPrefix({ params: { title: '' } })).toBe('');
    });


    it('writes the message out as XML with attributes in place and text escaped', () => {
        expect(fieldsToXml(IVANTI)).toBe([
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">',
            '  <soap:Header/>',
            '  <soap:Body>',
            '    <ListMachines xmlns="http://landesk.com/MBSDKService/MBSDK/">',
            '      <Filter>DeviceName = &quot;a&amp;b&quot;</Filter>',
            '    </ListMachines>',
            '  </soap:Body>',
            '</soap:Envelope>'
        ].join('\n'));
    });


    it('repeats an element for each entry of a list', () => {
        expect(fieldsToXml({ Device: [{ Name: 'a' }, { Name: 'b' }] }))
            .toBe('<Device>\n  <Name>a</Name>\n</Device>\n<Device>\n  <Name>b</Name>\n</Device>');
    });
});
