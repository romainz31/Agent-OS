import fs from 'node:fs'
import path from 'node:path'

import { getProfilePaths } from '@/core/profile-runtime/profile-paths'

import type { PaulContextPack } from './types'

export interface PaulLettaBridgeOptions {
  profileName?: string
  stateFilePath?: string
  fetchImpl?: typeof fetch
  baseUrl?: string
  token?: string
  enabled?: boolean
  agentId?: string
  model?: string
  timeoutMs?: number
}

export interface PaulLettaStatus {
  enabled: boolean
  configured: boolean
  reachable: boolean | null
  baseUrl: string
  agentId: string | null
  error: string | null
}

export interface PaulLettaReply {
  agentId: string
  content: string
  raw: unknown
}

interface LettaAgentState {
  agentId: string
  baseUrl: string
  createdAt: number
}

interface LettaBridgeOptions {
  input: string
  context: PaulContextPack
  sessionId?: string | null
}

function boolFromEnv(value: string | undefined): boolean {
  return value === '1' || value?.toLowerCase() === 'true' || value?.toLowerCase() === 'yes'
}

function normalizeBaseUrl(value: string): string {
  const normalized = value.trim().replace(/\/$/, '')
  return normalized.startsWith('ws://')
    ? `http://${normalized.slice('ws://'.length)}`
    : normalized.startsWith('wss://')
      ? `https://${normalized.slice('wss://'.length)}`
      : normalized
}

function textFromUnknown(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(textFromUnknown).filter(Boolean).join('')
  if (!value || typeof value !== 'object') return ''
  const record = value as Record<string, unknown>
  if (typeof record['text'] === 'string') return record['text']
  if (typeof record['content'] === 'string') return record['content']
  return ''
}

function assistantContent(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return ''
  const messages = (payload as Record<string, unknown>)['messages']
  if (!Array.isArray(messages)) return ''

  const assistantMessages = messages.filter((message) => {
    if (!message || typeof message !== 'object') return false
    const row = message as Record<string, unknown>
    return row['message_type'] === 'assistant_message' || row['role'] === 'assistant'
  })
  const candidates = assistantMessages.length ? assistantMessages : messages
  return candidates
    .map((message) => textFromUnknown(message))
    .filter(Boolean)
    .join('\n')
    .trim()
}

/**
 * Optional Letta adapter.
 *
 * Paul remains usable without Letta. When enabled, the adapter talks to the
 * self-hosted Letta HTTP API and injects Paul's structured context into each
 * turn. The local SQLite store remains the source of truth for exact dates,
 * counts and reminders; Letta supplies the durable conversational layer.
 */
export default class LettaBridge {
  private readonly profileName: string
  private readonly fetchImpl: typeof fetch
  private readonly baseUrl: string
  private readonly token: string | null
  private readonly enabled: boolean
  private readonly configuredAgentId: string | null
  private readonly model: string | null
  private readonly timeoutMs: number
  private readonly configuredStateFilePath: string | undefined

  public constructor(options: PaulLettaBridgeOptions = {}) {
    this.profileName = options.profileName || process.env['LEON_PROFILE'] || 'default'
    this.fetchImpl = options.fetchImpl || fetch
    this.baseUrl = normalizeBaseUrl(
      options.baseUrl || process.env['PAUL_LETTA_URL'] || process.env['LETTA_APP_SERVER_URL'] || 'http://127.0.0.1:4500'
    )
    this.token = options.token || process.env['PAUL_LETTA_TOKEN'] || process.env['LETTA_APP_SERVER_TOKEN'] || process.env['LETTA_API_KEY'] || null
    this.enabled = options.enabled ?? boolFromEnv(process.env['PAUL_LETTA_ENABLED'])
    this.configuredAgentId = options.agentId || process.env['PAUL_LETTA_AGENT_ID'] || null
    this.model = options.model || process.env['PAUL_LETTA_MODEL'] || process.env['LETTA_MODEL'] || null
    this.timeoutMs = options.timeoutMs || Number(process.env['PAUL_LETTA_TIMEOUT_MS'] || 20_000)
    this.configuredStateFilePath = options.stateFilePath
  }

  public get status(): PaulLettaStatus {
    const state = this.readState()
    return {
      enabled: this.enabled,
      configured: Boolean(this.configuredAgentId || state?.agentId),
      reachable: null,
      baseUrl: this.baseUrl,
      agentId: this.configuredAgentId || state?.agentId || null,
      error: null
    }
  }

  public async check(): Promise<PaulLettaStatus> {
    const status = this.status
    if (!this.enabled) return status

    try {
      await this.request('/readyz', { method: 'GET' })
      return { ...status, reachable: true }
    } catch (error) {
      return {
        ...status,
        reachable: false,
        error: error instanceof Error ? error.message : String(error)
      }
    }
  }

  public async chat(options: LettaBridgeOptions): Promise<PaulLettaReply> {
    if (!this.enabled) {
      throw new Error('Letta is disabled. Set PAUL_LETTA_ENABLED=true to enable the optional Letta layer.')
    }

    const agentId = await this.ensureAgent()
    const context = JSON.stringify(options.context, null, 2)
    const sessionHint = options.sessionId ? `Conversation session: ${options.sessionId}` : ''
    const input = [
      'You are Paul, a French-speaking personal assistant.',
      'Use the structured context below as authoritative for exact dates, counts, tasks and reminders.',
      'Do not invent missing facts. If a write is needed, ask Leon to execute the corresponding Paul action.',
      sessionHint,
      'STRUCTURED PAUL CONTEXT:',
      context,
      'USER MESSAGE:',
      options.input
    ].filter(Boolean).join('\n\n')

    const raw = await this.request(`/v1/agents/${encodeURIComponent(agentId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ input })
    })
    return {
      agentId,
      content: assistantContent(raw) || 'Letta n’a pas renvoyé de réponse textuelle.',
      raw
    }
  }

  private statePath(): string {
    return this.configuredStateFilePath || path.join(getProfilePaths(this.profileName).root, 'paul', 'letta-agent.json')
  }

  private readState(): LettaAgentState | null {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.statePath(), 'utf8')) as Partial<LettaAgentState>
      return typeof parsed.agentId === 'string' && typeof parsed.baseUrl === 'string' && typeof parsed.createdAt === 'number'
        ? parsed as LettaAgentState
        : null
    } catch {
      return null
    }
  }

  private writeState(agentId: string): void {
    const filePath = this.statePath()
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.writeFileSync(filePath, `${JSON.stringify({ agentId, baseUrl: this.baseUrl, createdAt: Date.now() }, null, 2)}\n`, 'utf8')
  }

  private async ensureAgent(): Promise<string> {
    const existing = this.configuredAgentId || this.readState()?.agentId
    if (existing) return existing

    const payload: Record<string, unknown> = {
      name: 'Paul',
      memory_blocks: [
        {
          label: 'human',
          value: 'The user is Romain. Paul is his private personal assistant. Prefer French and be precise with dates.'
        },
        {
          label: 'persona',
          value: 'You are Paul: calm, proactive, concise and honest. Keep durable conversational memory, but use Leon Paul structured data for exact facts and agenda.'
        }
      ]
    }
    if (this.model) payload['model'] = this.model

    const response = await this.request('/v1/agents', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
    const agentId = response && typeof response === 'object' && typeof (response as Record<string, unknown>)['id'] === 'string'
      ? String((response as Record<string, unknown>)['id'])
      : ''
    if (!agentId) throw new Error('Letta created an agent without returning an id.')
    this.writeState(agentId)
    return agentId
  }

  private async request(endpoint: string, init: RequestInit): Promise<unknown> {
    const headers = new Headers(init.headers)
    headers.set('content-type', 'application/json')
    if (this.token) headers.set('authorization', `Bearer ${this.token}`)

    const response = await this.fetchImpl(`${this.baseUrl}${endpoint}`, {
      ...init,
      headers,
      signal: init.signal || AbortSignal.timeout(this.timeoutMs)
    })
    const text = await response.text()
    let payload: unknown = null
    try {
      payload = text ? JSON.parse(text) : null
    } catch {
      payload = text
    }
    if (!response.ok) {
      const detail = typeof payload === 'string' ? payload : JSON.stringify(payload)
      throw new Error(`Letta request failed (${response.status}): ${detail}`)
    }
    return payload
  }
}
