import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import PaulStore from '@/core/paul/paul-store'
import { resolveDateRange } from '@/core/paul/temporal'

describe('PaulStore', () => {
  const stores: PaulStore[] = []
  const directories: string[] = []

  afterEach(() => {
    for (const store of stores.splice(0)) store.close()
    for (const directory of directories.splice(0)) fs.rmSync(directory, { recursive: true, force: true })
  })

  it('persists facts, relationships, dated activities and agenda items', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'paul-store-'))
    directories.push(directory)
    const now = Date.UTC(2026, 8, 10, 12)
    const store = new PaulStore({ databasePath: path.join(directory, 'paul.sqlite'), now: (): number => now })
    stores.push(store)
    store.initialize()

    const fact = store.addFact({ subject: 'Romain', predicate: 'a pour ville', value: 'Paris' })
    store.addRelationship({ subject: 'Coralie', relation: 'est la partenaire de', object: 'Romain' })
    const activity = store.recordActivity({ occurredAt: Date.UTC(2026, 8, 10, 9), action: 'joué', object: 'au tennis' })
    const agenda = store.createAgendaItem({
      kind: 'appointment',
      title: 'Dentiste',
      startAt: Date.UTC(2026, 8, 11, 8),
      sourceText: 'Dentiste demain matin'
    })

    const today = resolveDateRange('aujourd\'hui', new Date(now))
    const tomorrow = resolveDateRange('demain', new Date(now))
    expect(store.getFact(fact.id)?.value).toBe('Paris')
    expect(store.listRelationships()).toHaveLength(1)
    expect(store.listActivities(today)).toEqual([expect.objectContaining({ id: activity.id, action: 'joué' })])
    expect(store.listAgenda(tomorrow)).toEqual([expect.objectContaining({ id: agenda.id, title: 'Dentiste' })])
    expect(store.countActivities(today, 'jou', 'tennis')).toBe(1)
  })

  it('keeps the previous context for follow-up questions', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'paul-context-'))
    directories.push(directory)
    const store = new PaulStore({ databasePath: path.join(directory, 'paul.sqlite') })
    stores.push(store)
    store.saveConversationContext({
      sessionId: 'test-session',
      lastIntent: 'activity_count',
      lastDateRange: resolveDateRange('12/09/2026'),
      lastEntity: 'tennis',
      lastQuery: 'combien de fois',
      updatedAt: Date.now()
    })
    expect(store.getConversationContext('test-session')).toMatchObject({
      lastIntent: 'activity_count',
      lastEntity: 'tennis',
      lastDateRange: expect.objectContaining({ startDay: '2026-09-12' })
    })
  })
})
