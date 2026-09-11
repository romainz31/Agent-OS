import { describe, expect, it } from 'vitest'

import { inferDateRangeFromText, resolveDateRange } from '@/core/paul/temporal'

const NOW = new Date(Date.UTC(2026, 8, 10, 12, 30))

describe('Paul temporal resolver', () => {
  it('resolves French relative dates', () => {
    expect(resolveDateRange('demain', NOW).startDay).toBe('2026-09-11')
    expect(resolveDateRange('hier', NOW).startDay).toBe('2026-09-09')
    expect(resolveDateRange('cette semaine', NOW)).toMatchObject({
      startDay: '2026-09-07',
      endDay: '2026-09-13'
    })
  })

  it('resolves explicit dates and follow-up weekday expressions', () => {
    expect(resolveDateRange('12/09/2026', NOW).startDay).toBe('2026-09-12')
    expect(resolveDateRange('mercredi prochain', NOW, 'future').startDay).toBe('2026-09-16')
    expect(inferDateRangeFromText('Et le 12/09 alors ?', NOW)?.startDay).toBe('2026-09-12')
  })

  it('uses a deterministic fallback for unknown expressions', () => {
    expect(resolveDateRange('un jour quelconque', NOW).startDay).toBe('2026-09-10')
  })

  it('keeps calendar boundaries in the configured timezone', () => {
    const justAfterMidnight = new Date('2026-09-09T22:30:00.000Z')
    const range = resolveDateRange('aujourd\'hui', justAfterMidnight, 'nearest', 'Europe/Paris')
    expect(range.startDay).toBe('2026-09-10')
    expect(range.startAt).toBe(Date.parse('2026-09-09T22:00:00.000Z'))
    expect(range.endAt).toBe(Date.parse('2026-09-10T21:59:59.999Z'))
  })
})
