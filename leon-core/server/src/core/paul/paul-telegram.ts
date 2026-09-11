import { EventEmitter } from 'node:events'

import PaulService from './paul-service'

interface TelegramUpdate {
  update_id: number
  message?: {
    chat?: { id?: number | string }
    text?: string
  }
}

interface TelegramResponse<T> {
  ok: boolean
  result: T
  description?: string
}

const TELEGRAM_MAX_MESSAGE_LENGTH = 4_096

function splitMessage(message: string): string[] {
  if (message.length <= TELEGRAM_MAX_MESSAGE_LENGTH) return [message]
  const chunks: string[] = []
  for (let offset = 0; offset < message.length; offset += TELEGRAM_MAX_MESSAGE_LENGTH) {
    chunks.push(message.slice(offset, offset + TELEGRAM_MAX_MESSAGE_LENGTH))
  }
  return chunks
}

function formatAgenda(service: PaulService, expression: string): string {
  const range = service.resolveDate(expression)
  const program = service.getProgram(range)
  const lines = [
    `Programme du ${range.startDay}${range.startDay === range.endDay ? '' : ` au ${range.endDay}`}`
  ]
  const agenda = [
    ...program.tasks,
    ...program.appointments,
    ...program.events,
    ...program.reminders
  ]
  if (agenda.length === 0) lines.push('Rien de prévu.')
  for (const item of agenda) {
    const when = item.startAt || item.dueAt
    const time = when
      ? ` — ${new Date(when).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: item.timezone })}`
      : ''
    lines.push(`• [${item.kind}] ${item.title}${time}`)
  }
  if (program.activities.length) lines.push(`Activités enregistrées : ${program.activities.length}`)
  return lines.join('\n')
}

/**
 * Small dependency-free Telegram long-polling adapter.
 *
 * It is deliberately opt-in. Letta can still expose its own Telegram channel,
 * but this adapter keeps Paul's exact agenda and reminder delivery in Leon's
 * profile runtime and works with the same local database.
 */
export default class PaulTelegramBot {
  private readonly token: string | null
  private readonly allowedChatIds: Set<string>
  private readonly service = new PaulService()
  private readonly fetchImpl: typeof fetch
  private readonly events = new EventEmitter()
  private abortController: AbortController | null = null
  private running = false
  private offset = 0
  private notificationChatId: string | null

  public constructor(options: { fetchImpl?: typeof fetch } = {}) {
    this.token = process.env['PAUL_TELEGRAM_BOT_TOKEN'] || process.env['TELEGRAM_BOT_TOKEN'] || null
    this.allowedChatIds = new Set(
      (process.env['PAUL_TELEGRAM_ALLOWED_CHAT_IDS'] || '')
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
    )
    this.notificationChatId = process.env['PAUL_TELEGRAM_CHAT_ID'] || null
    this.fetchImpl = options.fetchImpl || fetch
  }

  public get isConfigured(): boolean {
    return Boolean(this.token)
  }

  public start(): void {
    if (this.running || !this.token) return
    this.running = true
    this.abortController = new AbortController()
    void this.pollLoop()
  }

  public stop(): void {
    this.running = false
    this.abortController?.abort()
    this.abortController = null
  }

  private async pollLoop(): Promise<void> {
    while (this.running && this.token) {
      try {
        const updates = await this.call<TelegramUpdate[]>('getUpdates', {
          offset: this.offset,
          timeout: 25,
          allowed_updates: ['message']
        }, true)
        for (const update of updates) {
          this.offset = Math.max(this.offset, update.update_id + 1)
          await this.handleUpdate(update)
        }
        await this.deliverNotifications()
      } catch (error) {
        if (!this.running) break
        this.events.emit('error', error)
        await new Promise((resolve) => setTimeout(resolve, 5_000))
      }
    }
  }

  private async handleUpdate(update: TelegramUpdate): Promise<void> {
    const message = update.message
    const chatId = message?.chat?.id
    const text = message?.text?.trim()
    if (chatId === undefined || !text) return

    const chatIdString = String(chatId)
    if (this.allowedChatIds.size && !this.allowedChatIds.has(chatIdString)) {
      await this.sendMessage(chatIdString, 'Ce bot Paul n’est pas autorisé pour cette conversation.')
      return
    }
    if (!this.notificationChatId) this.notificationChatId = chatIdString

    if (text === '/start' || text === '/help') {
      await this.sendMessage(chatIdString, [
        'Je suis Paul.',
        '/programme [date] — afficher le programme',
        '/rappels — afficher les rappels en attente',
        'Pour une conversation libre, activez PAUL_LETTA_ENABLED.'
      ].join('\n'))
      return
    }

    if (text.startsWith('/programme')) {
      await this.sendMessage(chatIdString, formatAgenda(this.service, text.slice('/programme'.length).trim() || 'aujourd\'hui'))
      return
    }

    if (text === '/rappels') {
      const notifications = this.service.getPendingNotifications()
      await this.sendMessage(chatIdString, notifications.length
        ? notifications.map((item) => `• ${String(item.payload['title'] || 'Rappel')}`).join('\n')
        : 'Aucun rappel en attente.')
      return
    }

    if (!this.service.getLettaStatus().enabled) {
      await this.sendMessage(chatIdString, 'Letta est désactivé. Utilisez /programme ou activez PAUL_LETTA_ENABLED pour le dialogue libre.')
      return
    }

    const response = await this.service.chatWithLetta(text)
    await this.sendMessage(chatIdString, response.content)
  }

  private async deliverNotifications(): Promise<void> {
    if (!this.notificationChatId) return
    for (const notification of this.service.getPendingNotifications()) {
      const title = String(notification.payload['title'] || 'Rappel')
      const description = String(notification.payload['description'] || '')
      await this.sendMessage(this.notificationChatId, `⏰ ${title}${description ? `\n${description}` : ''}`)
      this.service.markNotificationDelivered(notification.id)
    }
  }

  private async sendMessage(chatId: string, text: string): Promise<void> {
    for (const chunk of splitMessage(text)) {
      await this.call('sendMessage', { chat_id: chatId, text: chunk })
    }
  }

  private async call<T>(method: string, body: Record<string, unknown>, longPoll = false): Promise<T> {
    if (!this.token) throw new Error('Telegram bot token is not configured.')
    const requestInit: RequestInit = {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }
    if (longPoll && this.abortController?.signal) requestInit.signal = this.abortController.signal
    const response = await this.fetchImpl(`https://api.telegram.org/bot${this.token}/${method}`, requestInit)
    const payload = await response.json() as TelegramResponse<T>
    if (!response.ok || !payload.ok) {
      throw new Error(`Telegram request failed: ${payload.description || response.statusText}`)
    }
    return payload.result
  }
}
