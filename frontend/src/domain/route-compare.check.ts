import { openingAccessNote, spaceAccessNote } from './route-compare.ts'

const wide = openingAccessNote({ width_m: 3, step_free: true }, true)
const narrow = openingAccessNote({ width_m: 1.2, step_free: false }, true)
const plain = openingAccessNote({ width_m: 0.9, step_free: true }, false)
if (!wide.includes('Wide enough')) throw new Error('a 3 m door is wide enough for a forklift')
if (!narrow.includes('Too narrow') || !narrow.includes('1.2')) throw new Error('a narrow door must say it is people-only')
if (plain !== 'Step-free') throw new Error('forklift copy stays off until comparison is on')

const bay = spaceAccessNote('production_zone', 'Main aisle', true)
const office = spaceAccessNote('office', 'Desk', true)
if (!bay?.includes('cannot cross')) throw new Error('a production bay is destination-only for a forklift')
if (office !== 'Desk') throw new Error('ordinary rooms keep their own note')
