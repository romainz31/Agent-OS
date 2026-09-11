import axios from 'axios'

const DAY_LABELS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi']
const KIND_LABELS = {
  task: 'Tâche',
  appointment: 'Rendez-vous',
  event: 'Événement',
  reminder: 'Rappel'
}
const KIND_ICONS = {
  task: 'ri-checkbox-circle-line',
  appointment: 'ri-calendar-event-line',
  event: 'ri-star-line',
  reminder: 'ri-notification-3-line'
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  return new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(timestamp))
}

function formatDate(date) {
  return new Intl.DateTimeFormat('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric'
  }).format(date)
}

function getDateExpression(offset) {
  if (offset === 0) return 'aujourd\'hui'
  if (offset === 1) return 'demain'
  return `dans ${offset} jours`
}

function getDayLabel(offset, date) {
  if (offset === 0) return 'Aujourd\'hui'
  if (offset === 1) return 'Demain'
  return `${DAY_LABELS[date.getDay()]} ${date.getDate()}`
}

function createAgendaRow(item, { compact = false, onComplete } = {}) {
  const row = document.createElement('article')
  row.className = `paul-agenda-row${compact ? ' paul-agenda-row--compact' : ''}`
  row.dataset.itemId = item.id

  const icon = document.createElement('i')
  icon.className = KIND_ICONS[item.kind] || KIND_ICONS.task
  icon.setAttribute('aria-hidden', 'true')

  const content = document.createElement('div')
  content.className = 'paul-agenda-content'
  const title = document.createElement('strong')
  title.textContent = item.title
  const meta = document.createElement('span')
  meta.textContent = [KIND_LABELS[item.kind] || 'Élément', formatTime(item.startAt || item.dueAt)].filter(Boolean).join(' · ')
  content.append(title, meta)

  row.append(icon, content)

  if (item.status === 'completed') {
    row.classList.add('paul-agenda-row--completed')
  } else if (item.kind === 'task') {
    const button = document.createElement('button')
    button.className = 'paul-complete-button'
    button.type = 'button'
    button.title = 'Marquer comme terminé'
    button.textContent = '✓'
    button.addEventListener('click', async () => {
      button.disabled = true
      await onComplete?.(item.id)
    })
    row.appendChild(button)
  }

  return row
}

function setMessage(container, message, className = 'paul-empty') {
  container.replaceChildren()
  const element = document.createElement('p')
  element.className = className
  element.textContent = message
  container.appendChild(element)
}

export default class PaulDashboard {
  constructor({ serverUrl }) {
    this.serverUrl = serverUrl
    this.todayList = document.querySelector('#paul-today-list')
    this.weekList = document.querySelector('#paul-week-list')
    this.clock = document.querySelector('#paul-clock')
    this.date = document.querySelector('#paul-date')
    this.status = document.querySelector('#paul-status')
    this.refreshButton = document.querySelector('#paul-refresh')
    this.viewAllButton = document.querySelector('#paul-view-all')
  }

  init() {
    this.renderHeader()
    window.setInterval(() => this.renderHeader(), 1_000)
    this.refreshButton?.addEventListener('click', () => void this.refresh())
    this.viewAllButton?.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('paul:show-agenda'))
      this.weekList?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    void this.refresh()
  }

  renderHeader() {
    const now = new Date()
    if (this.date) this.date.textContent = formatDate(now)
    if (this.clock) {
      this.clock.textContent = new Intl.DateTimeFormat('fr-FR', {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      }).format(now)
    }
  }

  async refresh() {
    try {
      this.status?.classList.remove('paul-status--error')
      const agendaByDay = await Promise.all(
        Array.from({ length: 7 }, (_, offset) =>
          axios.get(`${this.serverUrl}/api/v1/paul/agenda`, {
            params: { date: getDateExpression(offset) }
          }).then((response) => response.data.items || [])
        )
      )

      this.renderToday(agendaByDay[0])
      this.renderWeek(agendaByDay)
    } catch (error) {
      console.error('Paul dashboard refresh failed:', error)
      this.status?.classList.add('paul-status--error')
      if (this.todayList) setMessage(this.todayList, 'Le programme de Paul est momentanément indisponible.')
      if (this.weekList) setMessage(this.weekList, 'Impossible de charger l’agenda.')
    }
  }

  renderToday(items) {
    if (!this.todayList) return
    this.todayList.replaceChildren()
    const openItems = items.filter((item) => item.status !== 'completed' && item.status !== 'cancelled')
    if (openItems.length === 0) {
      setMessage(this.todayList, 'Rien de prévu pour le moment. Tu peux me parler de ce que tu veux ajouter.')
      return
    }
    openItems.slice(0, 5).forEach((item) => {
      this.todayList.appendChild(createAgendaRow(item, {
        onComplete: (id) => this.complete(id)
      }))
    })
    if (openItems.length > 5) {
      const more = document.createElement('p')
      more.className = 'paul-more'
      more.textContent = `+ ${openItems.length - 5} autre(s) élément(s)`
      this.todayList.appendChild(more)
    }
  }

  renderWeek(agendaByDay) {
    if (!this.weekList) return
    this.weekList.replaceChildren()
    agendaByDay.forEach((items, offset) => {
      const date = new Date()
      date.setHours(12, 0, 0, 0)
      date.setDate(date.getDate() + offset)
      const day = document.createElement('section')
      day.className = `paul-day${offset === 0 ? ' paul-day--today' : ''}`
      const heading = document.createElement('h3')
      heading.textContent = getDayLabel(offset, date)
      const count = document.createElement('span')
      count.textContent = String(items.filter((item) => item.status !== 'cancelled').length)
      heading.appendChild(count)
      day.appendChild(heading)
      const visibleItems = items.filter((item) => item.status !== 'cancelled').slice(0, 3)
      if (visibleItems.length === 0) {
        const empty = document.createElement('p')
        empty.className = 'paul-day-empty'
        empty.textContent = 'Libre'
        day.appendChild(empty)
      } else {
        visibleItems.forEach((item) => day.appendChild(createAgendaRow(item, {
          compact: true,
          onComplete: (id) => this.complete(id)
        })))
      }
      this.weekList.appendChild(day)
    })
  }

  async complete(id) {
    try {
      await axios.post(`${this.serverUrl}/api/v1/paul/agenda/${id}/complete`)
      await this.refresh()
    } catch (error) {
      console.error('Paul agenda completion failed:', error)
      await this.refresh()
    }
  }
}
