import type { PaulDateRange } from './types'

const WEEKDAYS: Record<string, number> = {
  dimanche: 0,
  dimanchee: 0,
  lundi: 1,
  mardi: 2,
  mercredi: 3,
  jeudi: 4,
  vendredi: 5,
  samedi: 6
}

const MONTHS: Record<string, number> = {
  janvier: 0,
  fevrier: 1,
  février: 1,
  mars: 2,
  avril: 3,
  mai: 4,
  juin: 5,
  juillet: 6,
  aout: 7,
  août: 7,
  septembre: 8,
  octobre: 9,
  novembre: 10,
  decembre: 11,
  décembre: 11
}

function normalize(value: string): string {
  return value
    .toLocaleLowerCase('fr-FR')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function dayKey(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
}

function parseDayKey(value: string): Date {
  return new Date(`${value}T00:00:00.000Z`)
}

function calendarParts(date: Date, timezone: string): { year: number, month: number, day: number, hour: number, minute: number, second: number } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return {
    year: Number(values['year']),
    month: Number(values['month']),
    day: Number(values['day']),
    hour: Number(values['hour']),
    minute: Number(values['minute']),
    second: Number(values['second'])
  }
}

function zonedMidnight(day: string, timezone: string): Date {
  const calendar = parseDayKey(day)
  const guess = calendar.getTime()
  const represented = calendarParts(new Date(guess), timezone)
  const representedAsUtc = Date.UTC(represented.year, represented.month - 1, represented.day, represented.hour, represented.minute, represented.second)
  const firstPass = guess - (representedAsUtc - guess)
  const corrected = calendarParts(new Date(firstPass), timezone)
  const correctedAsUtc = Date.UTC(corrected.year, corrected.month - 1, corrected.day, corrected.hour, corrected.minute, corrected.second)
  return new Date(guess - (correctedAsUtc - firstPass))
}

export function dayKeyInTimezone(timestamp: number, timezone = process.env['PAUL_TIMEZONE'] || 'Europe/Paris'): string {
  const parts = calendarParts(new Date(timestamp), timezone)
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`
}

function addDays(date: Date, amount: number): Date {
  const result = new Date(date.getTime())
  result.setUTCDate(result.getUTCDate() + amount)
  return result
}

function startOfWeek(date: Date): Date {
  const result = new Date(date.getTime())
  const mondayOffset = (result.getUTCDay() + 6) % 7
  result.setUTCDate(result.getUTCDate() - mondayOffset)
  return result
}

function toRange(start: Date, end: Date, expression: string | null, timezone: string): PaulDateRange {
  const startDay = dayKey(start)
  const endDay = dayKey(end)
  const startAt = zonedMidnight(startDay, timezone).getTime()
  const nextDay = dayKey(addDays(parseDayKey(endDay), 1))
  const endAt = zonedMidnight(nextDay, timezone).getTime() - 1

  return {
    startDay,
    endDay,
    startAt,
    endAt,
    expression
  }
}

function resolveWeekday(
  target: number,
  now: Date,
  direction: 'past' | 'future' | 'nearest'
): Date {
  const current = now.getUTCDay()
  let delta = target - current

  if (direction === 'past' && delta >= 0) {
    delta -= 7
  }
  if (direction === 'future' && delta <= 0) {
    delta += 7
  }
  if (direction === 'nearest' && Math.abs(delta) > 3) {
    delta += delta > 0 ? -7 : 7
  }

  return addDays(now, delta)
}

function parseExplicitDate(expression: string, now: Date): Date | null {
  const numeric = expression.match(/\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b/)
  if (numeric) {
    const day = Number(numeric[1])
    const month = Number(numeric[2]) - 1
    const rawYear = numeric[3]
    const year = rawYear
      ? rawYear.length === 2
        ? 2000 + Number(rawYear)
        : Number(rawYear)
      : now.getUTCFullYear()
    if (day >= 1 && day <= 31 && month >= 0 && month <= 11) {
      return new Date(Date.UTC(year, month, day))
    }
  }

  const written = normalize(expression).match(
    /\b(\d{1,2})\s+(?:de\s+)?([a-zéû]+)(?:\s+(\d{4}))?\b/
  )
  if (written) {
    const month = MONTHS[written[2] || '']
    if (month !== undefined) {
      return new Date(Date.UTC(
        written[3] ? Number(written[3]) : now.getUTCFullYear(),
        month,
        Number(written[1])
      ))
    }
  }

  return null
}

export function resolveDateRange(
  expression: string | null | undefined,
  now = new Date(),
  direction: 'past' | 'future' | 'nearest' = 'nearest',
  timezone = process.env['PAUL_TIMEZONE'] || 'Europe/Paris'
): PaulDateRange {
  const raw = String(expression || '').trim()
  const value = normalize(raw)
  const todayParts = calendarParts(now, timezone)
  const today = new Date(Date.UTC(todayParts.year, todayParts.month - 1, todayParts.day))

  if (!value || value === 'aujourd\'hui' || value === 'aujourd hui' || value === 'ce jour') {
    return toRange(today, today, raw || null, timezone)
  }
  if (value === 'demain' || value === 'le lendemain') {
    const date = addDays(today, 1)
    return toRange(date, date, raw, timezone)
  }
  if (value === 'hier' || value === 'la veille') {
    const date = addDays(today, -1)
    return toRange(date, date, raw, timezone)
  }

  const relative = value.match(/(?:dans|d'ici|d ici)\s+(\d+)\s+jours?/) 
  if (relative) {
    const date = addDays(today, Number(relative[1]))
    return toRange(date, date, raw, timezone)
  }

  if (value.includes('cette semaine') || value === 'la semaine') {
    const start = startOfWeek(today)
    return toRange(start, addDays(start, 6), raw, timezone)
  }
  if (value.includes('semaine derniere')) {
    const end = addDays(startOfWeek(today), -1)
    return toRange(addDays(end, -6), end, raw, timezone)
  }
  if (value.includes('semaine prochaine')) {
    const start = addDays(startOfWeek(today), 7)
    return toRange(start, addDays(start, 6), raw, timezone)
  }
  if (value.includes('ce mois') || value.includes('ce mois-ci')) {
    const start = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1))
    const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + 1, 0))
    return toRange(start, end, raw, timezone)
  }

  const explicit = parseExplicitDate(value, today)
  if (explicit) {
    return toRange(explicit, explicit, raw, timezone)
  }

  const weekdayExpression = value.match(
    /\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b/
  )
  if (weekdayExpression) {
    const weekday = WEEKDAYS[weekdayExpression[0]]
    if (weekday === undefined) return toRange(today, today, raw || null, timezone)
    const weekdayDirection = value.includes('prochain') || value.includes('suivant')
      ? 'future'
      : value.includes('dernier') || value.includes('passe')
        ? 'past'
        : direction
    const date = resolveWeekday(weekday, today, weekdayDirection)
    return toRange(date, date, raw, timezone)
  }

  return toRange(today, today, raw || null, timezone)
}

export function inferDateRangeFromText(
  text: string,
  now = new Date(),
  direction: 'past' | 'future' | 'nearest' = 'nearest',
  timezone = process.env['PAUL_TIMEZONE'] || 'Europe/Paris'
): PaulDateRange | null {
  const normalized = normalize(text)
  const patterns = [
    /aujourd'hui|aujourd hui|ce jour|demain|hier|la veille/,
    /dans\s+\d+\s+jours?/,
    /cette semaine|semaine derniere|semaine prochaine|ce mois(?:-ci)?/,
    /\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b/,
    /\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b/
  ]
  const matched = patterns.find((pattern) => pattern.test(normalized))
  return matched ? resolveDateRange(normalized.match(matched)?.[0], now, direction, timezone) : null
}

export function formatFrenchDate(day: string): string {
  return new Intl.DateTimeFormat('fr-FR', {
    dateStyle: 'long',
    timeZone: 'UTC'
  }).format(parseDayKey(day))
}
