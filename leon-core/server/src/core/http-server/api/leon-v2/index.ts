import type { FastifyPluginAsync } from 'fastify'

import type { APIOptions } from '@/core/http-server/http-server'
import { ProfileHelper } from '@/helpers/profile-helper'
import { SkillDomainHelper } from '@/helpers/skill-domain-helper'
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

export const leonV2Plugin: FastifyPluginAsync<APIOptions> = async (
  fastify,
  options
) => {
  fastify.get(`/api/${options.apiVersion}/leon-v2/dashboard`, async (_request, reply) => {
    const now = new Date()

    return reply.send({
      success: true,
      assistant: 'Leon',
      status: 'ready',
      generated_at: now.toISOString(),
      tasks: [],
      agenda: []
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
