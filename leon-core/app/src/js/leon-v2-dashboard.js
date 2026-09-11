const API_VERSION = 'v1'

function escapeHTML(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function getEndpoint(serverUrl, path) {
  return `${serverUrl}/api/${API_VERSION}/leon-v2/${path}`
}

function getDateFormatter(timeZone) {
  return new Intl.DateTimeFormat('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone
  })
}

function getTimeFormatter(timeZone) {
  return new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone
  })
}

function renderListItem(item, type) {
  const title = escapeHTML(item.title || item.label || item.name || 'Élément')
  const detail = escapeHTML(item.time || item.date || item.description || '')
  const icon = type === 'task' ? 'ri-checkbox-circle-line' : 'ri-calendar-event-line'

  return `<div class="leon-v2-list-item">
    <i class="${icon}" aria-hidden="true"></i>
    <div><strong>${title}</strong>${detail ? `<span>${detail}</span>` : ''}</div>
  </div>`
}

function renderDashboard(payload) {
  const todayList = document.querySelector('#leon-v2-today-list')
  const weekList = document.querySelector('#leon-v2-week-list')

  if (!todayList || !weekList) {
    return
  }

  const tasks = Array.isArray(payload?.tasks) ? payload.tasks : []
  const agenda = Array.isArray(payload?.agenda) ? payload.agenda : []

  todayList.innerHTML = tasks.length
    ? tasks.map((item) => renderListItem(item, 'task')).join('')
    : 'Aucune tâche prévue pour aujourd’hui.'

  weekList.innerHTML = agenda.length
    ? agenda.map((item) => renderListItem(item, 'agenda')).join('')
    : '<div class="leon-v2-empty-state">Aucun rendez-vous ou événement prévu.</div>'
}

function renderPanelMessage(title, message) {
  return `<div class="leon-v2-empty-panel"><strong>${escapeHTML(title)}</strong><p>${escapeHTML(message)}</p></div>`
}

function renderSkillCard(skill) {
  const actions = Array.isArray(skill.actions) ? skill.actions : []
  const actionSummary = actions.length
    ? `${actions.length} action${actions.length > 1 ? 's' : ''}`
    : 'Aucune action détaillée'
  const actionDetails = actions.length
    ? actions.map((action) => `<li><strong>${escapeHTML(action.id)}</strong> — ${escapeHTML(action.description)}</li>`).join('')
    : '<li>Ce Skill fournit ses instructions directement à Leon.</li>'
  const status = skill.enabled ? 'Activé' : 'Désactivé'
  const toggleLabel = skill.enabled ? 'Désactiver' : 'Activer'

  return `<article class="leon-v2-skill-card${skill.enabled ? '' : ' is-disabled'}" data-skill-id="${escapeHTML(skill.id)}">
    <div class="leon-v2-skill-card-heading">
      <div>
        <div class="leon-v2-skill-name"><i class="ri-${escapeHTML(skill.iconName || 'apps-ai-line')}" aria-hidden="true"></i> ${escapeHTML(skill.name)}</div>
        <div class="leon-v2-skill-card-meta"><span>${escapeHTML(skill.format)}</span><span>•</span><span>${escapeHTML(skill.mode)} / ${escapeHTML(skill.bridge)}</span></div>
      </div>
      <span class="leon-v2-skill-status">${status}</span>
    </div>
    <p class="leon-v2-skill-description">${escapeHTML(skill.description)}</p>
    <div class="leon-v2-skill-card-actions">
      <span class="leon-v2-skill-action-count">${actionSummary}</span>
      <div>
        <button type="button" class="leon-v2-skill-details">Détails</button>
        <button type="button" class="leon-v2-skill-toggle">${toggleLabel}</button>
      </div>
    </div>
    <div class="leon-v2-skill-actions"><ul>${actionDetails}</ul></div>
  </article>`
}

function createPanelController(serverUrl) {
  const panel = document.querySelector('#leon-v2-panel')
  const backdrop = document.querySelector('#leon-v2-panel-backdrop')
  const title = document.querySelector('#leon-v2-panel-title')
  const content = document.querySelector('#leon-v2-panel-content')
  const closeButton = document.querySelector('#leon-v2-panel-close')

  if (!panel || !backdrop || !title || !content || !closeButton) {
    return null
  }

  function close() {
    panel.classList.add('leon-v2-hidden')
    backdrop.classList.add('leon-v2-hidden')
    backdrop.setAttribute('aria-hidden', 'true')
  }

  function open(panelName) {
    const labels = {
      settings: 'Paramètres',
      memory: 'Mémoire',
      skills: 'Skills',
      missions: 'Missions'
    }
    title.textContent = labels[panelName] || 'Leon'
    panel.classList.remove('leon-v2-hidden')
    backdrop.classList.remove('leon-v2-hidden')
    backdrop.setAttribute('aria-hidden', 'false')

    if (panelName === 'skills') {
      void loadSkills()
      return
    }

    const messages = {
      settings: ['Réglages de Leon', 'Les réglages détaillés seront branchés sur la configuration du profil.'],
      memory: ['Mémoire de Leon', 'Cette vue sera reliée à la mémoire native de Leon, sans recopier une mémoire parallèle.'],
      missions: ['Missions de Leon', 'Les missions et leur progression seront affichées ici lorsqu’une mission sera lancée.']
    }
    const [messageTitle, message] = messages[panelName] || ['Leon', 'Vue indisponible.']
    content.innerHTML = renderPanelMessage(messageTitle, message)
  }

  async function loadSkills() {
    content.innerHTML = renderPanelMessage('Chargement des Skills', 'Leon récupère les compétences réellement installées…')

    try {
      const response = await fetch(getEndpoint(serverUrl, 'skills'))
      const payload = await response.json()
      const skills = Array.isArray(payload.skills) ? payload.skills : []

      content.innerHTML = `<p class="leon-v2-panel-intro">Les Skills sont les capacités internes de Leon. Tu peux voir leurs actions et contrôler celles qui sont disponibles.</p>
        <div class="leon-v2-skill-toolbar"><input id="leon-v2-skill-search" type="search" placeholder="Rechercher un Skill…" aria-label="Rechercher un Skill" /></div>
        <div id="leon-v2-skill-grid" class="leon-v2-skill-grid">${skills.map(renderSkillCard).join('')}</div>`

      const grid = document.querySelector('#leon-v2-skill-grid')
      const search = document.querySelector('#leon-v2-skill-search')

      search?.addEventListener('input', () => {
        const query = search.value.trim().toLowerCase()
        grid?.querySelectorAll('.leon-v2-skill-card').forEach((card) => {
          const matches = !query || card.textContent.toLowerCase().includes(query)
          card.classList.toggle('leon-v2-hidden', !matches)
        })
      })

      grid?.addEventListener('click', async (event) => {
        const target = event.target.closest('button')
        const card = target?.closest('.leon-v2-skill-card')

        if (!target || !card) {
          return
        }

        if (target.classList.contains('leon-v2-skill-details')) {
          card.classList.toggle('is-expanded')
          return
        }

        if (!target.classList.contains('leon-v2-skill-toggle')) {
          return
        }

        const skillId = card.dataset.skillId
        const enabled = !card.classList.contains('is-disabled')
        target.disabled = true

        try {
          await fetch(`${serverUrl}/api/${API_VERSION}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              mode: 'execute',
              input: `/skill ${enabled ? 'disable' : 'enable'} ${skillId}`
            })
          })
          await loadSkills()
        } finally {
          target.disabled = false
        }
      })
    } catch (error) {
      content.innerHTML = renderPanelMessage('Skills indisponibles', error.message || 'Leon n’a pas pu charger ses Skills.')
    }
  }

  closeButton.addEventListener('click', close)
  backdrop.addEventListener('click', close)
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      close()
    }
  })
  document.querySelectorAll('[data-leon-panel]').forEach((button) => {
    button.addEventListener('click', () => open(button.dataset.leonPanel))
  })

  return { open, close }
}

export async function initLeonV2Dashboard({ serverUrl, timeZone = 'Europe/Paris' }) {
  document.body.classList.add('leon-v2')

  const dateElement = document.querySelector('#leon-v2-date')
  const clockElement = document.querySelector('#leon-v2-clock')
  const dateFormatter = getDateFormatter(timeZone)
  const timeFormatter = getTimeFormatter(timeZone)

  function updateClock() {
    const now = new Date()
    if (dateElement) dateElement.textContent = dateFormatter.format(now)
    if (clockElement) clockElement.textContent = timeFormatter.format(now)
  }

  updateClock()
  window.setInterval(updateClock, 1_000)
  createPanelController(serverUrl)

  try {
    const response = await fetch(getEndpoint(serverUrl, 'dashboard'))
    renderDashboard(await response.json())
  } catch {
    renderDashboard({ tasks: [], agenda: [] })
  }
}
