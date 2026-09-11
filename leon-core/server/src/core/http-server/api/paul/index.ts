import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from 'fastify'

import type { APIOptions } from '@/core/http-server/http-server'
import { PAUL_SERVICE } from '@/core'
import { resolveDateRange } from '@/core/paul/temporal'

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function queryValue(request: FastifyRequest, key: string, fallback: string): string {
  const query = record(request.query)
  const value = query[key]
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function sendError(reply: FastifyReply, error: unknown): void {
  reply.code(400).send({
    success: false,
    error: error instanceof Error ? error.message : String(error)
  })
}

export const paulPlugin: FastifyPluginAsync<APIOptions> = async (fastify, options) => {
  fastify.get(`/api/${options.apiVersion}/paul/summary`, async (request, reply) => {
    try {
      const range = resolveDateRange(queryValue(request, 'date', 'aujourd\'hui'))
      reply.send({ success: true, range, program: PAUL_SERVICE.getProgram(range), context: PAUL_SERVICE.getContextPack(range) })
    } catch (error) {
      sendError(reply, error)
    }
  })

  fastify.get(`/api/${options.apiVersion}/paul/agenda`, async (request, reply) => {
    try {
      const range = resolveDateRange(queryValue(request, 'date', 'aujourd\'hui'))
      const includeCompleted = queryValue(request, 'includeCompleted', 'false') === 'true'
      reply.send({ success: true, range, items: PAUL_SERVICE.queryAgenda(range, includeCompleted) })
    } catch (error) {
      sendError(reply, error)
    }
  })

  fastify.get(`/api/${options.apiVersion}/paul/activities`, async (request, reply) => {
    try {
      const range = resolveDateRange(queryValue(request, 'date', 'ce mois-ci'), new Date(), 'past')
      const query = record(request.query)
      const action = typeof query['action'] === 'string' ? query['action'] : undefined
      const object = typeof query['object'] === 'string' ? query['object'] : undefined
      reply.send({ success: true, range, activities: PAUL_SERVICE.queryActivities(range, action, object) })
    } catch (error) {
      sendError(reply, error)
    }
  })

  fastify.get(`/api/${options.apiVersion}/paul/count`, async (request, reply) => {
    try {
      const range = resolveDateRange(queryValue(request, 'date', 'ce mois-ci'), new Date(), 'past')
      const query = record(request.query)
      const action = typeof query['action'] === 'string' ? query['action'] : undefined
      const object = typeof query['object'] === 'string' ? query['object'] : undefined
      reply.send({ success: true, range, count: PAUL_SERVICE.countActivities(range, action, object), action: action || null, object: object || null })
    } catch (error) {
      sendError(reply, error)
    }
  })

  fastify.get(`/api/${options.apiVersion}/paul/letta`, async (_request, reply) => {
    reply.send({ success: true, letta: await PAUL_SERVICE.checkLetta() })
  })

  fastify.post(`/api/${options.apiVersion}/paul/chat`, async (request, reply) => {
    try {
      const body = record(request.body)
      const input = typeof body['input'] === 'string' ? body['input'].trim() : ''
      if (!input) {
        reply.code(400).send({ success: false, error: 'The "input" field is required.' })
        return
      }
      reply.send({ success: true, ...(await PAUL_SERVICE.chatWithLetta(input)) })
    } catch (error) {
      sendError(reply, error)
    }
  })

  fastify.post(`/api/${options.apiVersion}/paul/facts`, async (request, reply) => {
    try { reply.send({ success: true, fact: PAUL_SERVICE.addFact(record(request.body) as never) }) } catch (error) { sendError(reply, error) }
  })

  fastify.post(`/api/${options.apiVersion}/paul/relationships`, async (request, reply) => {
    try { reply.send({ success: true, relationship: PAUL_SERVICE.addRelationship(record(request.body) as never) }) } catch (error) { sendError(reply, error) }
  })

  fastify.post(`/api/${options.apiVersion}/paul/activities`, async (request, reply) => {
    try { reply.send({ success: true, activity: PAUL_SERVICE.recordActivity(record(request.body) as never) }) } catch (error) { sendError(reply, error) }
  })

  fastify.post(`/api/${options.apiVersion}/paul/agenda`, async (request, reply) => {
    try { reply.send({ success: true, agendaItem: PAUL_SERVICE.createAgendaItem(record(request.body) as never) }) } catch (error) { sendError(reply, error) }
  })

  fastify.post(`/api/${options.apiVersion}/paul/mood`, async (request, reply) => {
    try { reply.send({ success: true, mood: PAUL_SERVICE.recordMood(record(request.body) as never) }) } catch (error) { sendError(reply, error) }
  })

  fastify.post(`/api/${options.apiVersion}/paul/habits`, async (request, reply) => {
    try { reply.send({ success: true, habit: PAUL_SERVICE.upsertHabit(record(request.body) as never) }) } catch (error) { sendError(reply, error) }
  })

  fastify.post<{ Params: { id: string } }>(`/api/${options.apiVersion}/paul/agenda/:id/complete`, async (request, reply) => {
    try {
      const result = PAUL_SERVICE.completeAgendaItem(request.params.id)
      if (!result) {
        reply.code(404).send({ success: false, error: 'Agenda item not found.' })
        return
      }
      reply.send({ success: true, agendaItem: result })
    } catch (error) { sendError(reply, error) }
  })
}
