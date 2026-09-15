import { MappingControlPipe } from './mapping-control.pipe';

/**
 * The mapping step uses this pipe to split the available controls into properties and fields.
 * It must never throw on the empty states the wizard passes while nothing is loaded yet.
 */
describe('MappingControlPipe (mapping control filter)', () => {
    let pipe: MappingControlPipe;

    const controls = [
        { name: 'public_id', type: 'property' },
        { name: 'active', type: 'property' },
        { name: 'hostname', type: 'field' }
    ];

    beforeEach(() => pipe = new MappingControlPipe());

    it('keeps only the controls of the requested kind', () => {
        expect(pipe.transform(controls as any, 'type', 'property')).toEqual([
            { name: 'public_id', type: 'property' },
            { name: 'active', type: 'property' }
        ]);
    });

    it('returns an empty list when no control matches', () => {
        expect(pipe.transform(controls as any, 'type', 'ref')).toEqual([]);
    });

    it('passes the value through while the controls are not loaded yet', () => {
        expect(pipe.transform(undefined as any, 'type', 'property')).toBeUndefined();
        expect(pipe.transform(null as any, 'type', 'property')).toBeNull();
    });

    it('passes the list through when no property to filter on was given', () => {
        expect(pipe.transform(controls as any, '', 'property')).toBe(controls as any);
    });

    it('matches strictly, a numeric value does not match its string form', () => {
        const mapping = [{ value: 0 }, { value: 1 }];

        expect(pipe.transform(mapping as any, 'value', '0' as any)).toEqual([]);
        expect(pipe.transform(mapping as any, 'value', 0 as any)).toEqual([{ value: 0 }]);
    });

    it('is impure, so a mapping change is reflected on the next run', () => {
        const mapping: { type: string }[] = [{ type: 'property' }];

        expect(pipe.transform(mapping as any, 'type', 'property').length).toBe(1);

        mapping.push({ type: 'property' });
        expect(pipe.transform(mapping as any, 'type', 'property').length).toBe(2);
    });
});
