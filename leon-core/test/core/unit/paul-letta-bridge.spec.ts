import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import LettaBridge from '@/core/paul/letta-bridge'

describe('LettaBridge', () => {
  it('stays inert when disabled', async () => {
    const fetchImpl = vi.fn()
    const bridge = new LettaBridge({ enabled: false, fetchImpl })
    expect((await bridge.check()).reachable).toBeNull()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('creates an agent once and extracts its assistant reply', async () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'paul-letta-'))
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'agent-paul' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        messages: [
          { message_type: 'reasoning_message', reasoning: 'private' },
          { message_type: 'assistant_message', content: 'Bonjour Romain.' }
        ]
      }), { status: 200 }))

    const bridge = new LettaBridge({
      enabled: true,
      baseUrl: 'http://127.0.0.1:4500',
      fetchImpl,
      profileName: `paul-test-${path.basename(directory)}`,
      stateFilePath: path.join(directory, 'letta-agent.json')
    })
    const result = await bridge.chat({
      input: 'Bonjour',
      context: {
        today: '2026-09-10',
        profile: { facts: [], relationships: [] },
        agenda: [],
        recentActivities: [],
        recentMoods: [],
        pendingReminders: [],
        previousContext: null
      }
    })

    expect(result).toMatchObject({ agentId: 'agent-paul', content: 'Bonjour Romain.' })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    fs.rmSync(directory, { recursive: true, force: true })
  })
})
