import type { FastifyPluginAsync } from 'fastify'

import type { APIOptions } from '@/core/http-server/http-server'
import { MEMORY_MANAGER } from '@/core'
import { DateHelper } from '@/helpers/date-helper'
import { ProfileHelper } from '@/helpers/profile-helper'
import { SkillDomainHelper } from '@/helpers/skill-domain-helper'
import type { MemoryRecord } from '@/core/memory-manager/types'
import { SkillFormat } from '@/types'

interface SkillActionView {
  id: string
  type: string
  description: string
}

function getActions(skillId: string): SkillActionView[] {
  const config = SkillDomainHelper.getNewSkillConfigSync(skillId, {
    includeDisabled: true
  }) as {
    actions?: Record<string, {
      type?: string
      description?: string
    }>
  } | null

  if (!config?.actions || typeof config.actions !== 'object') {
    return []
  }

  return Object.entries(config.actions).map(([id, action]) => ({
    id,
    type: action?.type || 'action',
    description: action?.description || 'Action Leon disponible.'
  }))
}

function toSkillView(descriptor: ReturnType<typeof SkillDomainHelper.listAllSkillDescriptorsSync>[number]) {
  const isNative = descriptor.format === SkillFormat.LeonNative

  return {
    id: descriptor.id,
    name: descriptor.name,
    description: descriptor.description,
    iconName: descriptor.iconName,
    version: descriptor.version,
    format: isNative ? 'Leon natif' : 'Skill guidé',
    mode: 'Local',
    bridge: isNative
      ? String((SkillDomainHelper.getNewSkillConfigSync(descriptor.id, {
          includeDisabled: true
        }) as { bridge?: string | null } | null)?.bridge || 'Leon')
      : 'Instructions locales',
    enabled: !ProfileHelper.isSkillDisabled(descriptor.id),
    actions: getActions(descriptor.id)
  }
}

function addDays(dayKey: string, days: number): string {
  const date = new Date(`${dayKey}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function getMetadataString(
  metadata: Record<string, unknown>,
  key: string
): string | null {
  const value = metadata[key]
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function toDashboardItem(record: MemoryRecord) {
  const metadata = record.metadata || {}
  const date =
    getMetadataString(metadata, 'dueDate') ||
    getMetadataString(metadata, 'eventDate') ||
    record.dayKey
  const time =
    getMetadataString(metadata, 'dueTime') ||
    getMetadataString(metadata, 'eventTime')
  const title = record.title || record.content

  return {
    id: record.id,
    title,
    description: record.content,
    date,
    time,
    status: getMetadataString(metadata, 'status') || 'open',
    createdAt: record.createdAt,
    updatedAt: record.updatedAt
  }
}

export const leonV2Plugin: FastifyPluginAsync<APIOptions> = async (
  fastify,
  options
) => {
  fastify.get(`/api/${options.apiVersion}/leon-v2/dashboard`, async (_request, reply) => {
    const now = new Date()
    const today = DateHelper.getDateTime().slice(0, 10)
    const weekEnd = addDays(today, 7)
    const records = await MEMORY_MANAGER.listRecords({
      kinds: ['task', 'event'],
      limit: 200
    })
    const tasks = records
      .filter((record) => record.kind === 'task')
      .map(toDashboardItem)
      .filter((task) => task.status !== 'done' && (!task.date || task.date === today))
      .sort((left, right) => left.updatedAt - right.updatedAt)
    const agenda = records
      .filter((record) => record.kind === 'event')
      .map(toDashboardItem)
      .filter((event) => event.date !== null && event.date >= today && event.date <= weekEnd)
      .sort((left, right) => `${left.date || ''}${left.time || ''}`.localeCompare(`${right.date || ''}${right.time || ''}`))

    return reply.send({
      success: true,
      assistant: 'Leon',
      status: 'ready',
      generated_at: now.toISOString(),
      tasks,
      agenda
    })
  })

  fastify.get(`/api/${options.apiVersion}/leon-v2/skills`, async (_request, reply) => {
    const skills = SkillDomainHelper.listAllSkillDescriptorsSync().map(toSkillView)

    return reply.send({
      success: true,
      assistant: 'Leon',
      skills
    })
  })
}
