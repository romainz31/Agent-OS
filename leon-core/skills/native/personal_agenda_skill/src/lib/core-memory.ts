import MemoryManager from '@/core/memory-manager'

const memoryManager = new MemoryManager()

export async function saveAgendaEvent(input: {
  title: string
  date: string
  time?: string
}): Promise<void> {
  await memoryManager.remember({
    scope: 'persistent',
    kind: 'event',
    title: input.title,
    content: `Événement : ${input.title}`,
    sourceType: 'explicit_user',
    importance: 0.85,
    confidence: 0.95,
    dayKey: input.date,
    tags: ['agenda', 'personnel'],
    metadata: {
      category: 'personal_agenda',
      eventDate: input.date,
      ...(input.time ? { eventTime: input.time } : {})
    }
  })
}

export async function saveTask(input: {
  title: string
  date?: string
}): Promise<void> {
  await memoryManager.remember({
    scope: 'persistent',
    kind: 'task',
    title: input.title,
    content: `Tâche : ${input.title}`,
    sourceType: 'explicit_user',
    importance: 0.8,
    confidence: 0.95,
    ...(input.date ? { dayKey: input.date } : {}),
    tags: ['tache', 'personnel'],
    metadata: {
      category: 'personal_task',
      ...(input.date ? { dueDate: input.date } : {}),
      status: 'open'
    }
  })
}
