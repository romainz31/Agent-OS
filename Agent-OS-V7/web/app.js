const state = {
    dashboard: null,
    filter: "all",
    selectedMissionId: null,
    refreshBusy: false,
    chatBusy: false,
    notificationBusy: false,
    actionBusy: new Set(),
};

const CHAT_STORAGE_KEY = "agentos_v4_chat";

const elements = {
    networkBanner:
        document.getElementById("networkBanner"),

    serverState:
        document.getElementById("serverState"),

    versionBadge:
        document.getElementById("versionBadge"),

    statActiveMissions:
        document.getElementById("statActiveMissions"),

    statBusyAgents:
        document.getElementById("statBusyAgents"),

    statApprovals:
        document.getElementById("statApprovals"),

    statTotalMissions:
        document.getElementById("statTotalMissions"),

    chatMessages:
        document.getElementById("chatMessages"),

    chatForm:
        document.getElementById("chatForm"),

    chatInput:
        document.getElementById("chatInput"),

    sendButton:
        document.getElementById("sendButton"),

    clearChatButton:
        document.getElementById("clearChatButton"),

    missionList:
        document.getElementById("missionList"),

    missionFilters:
        document.getElementById("missionFilters"),

    refreshButton:
        document.getElementById("refreshButton"),

    agentGrid:
        document.getElementById("agentGrid"),

    approvalList:
        document.getElementById("approvalList"),

    approvalCountBadge:
        document.getElementById("approvalCountBadge"),

    missionDrawer:
        document.getElementById("missionDrawer"),

    drawerBackdrop:
        document.getElementById("drawerBackdrop"),

    drawerClose:
        document.getElementById("drawerClose"),

    drawerMissionId:
        document.getElementById("drawerMissionId"),

    drawerTitle:
        document.getElementById("drawerTitle"),

    drawerContent:
        document.getElementById("drawerContent"),

    toastStack:
        document.getElementById("toastStack"),
};


const missionStatusLabels = {
    planning: "Préparation",
    queued: "En attente",
    running: "En cours",
    waiting_approval: "Approbation",
    paused: "En pause",
    completed: "Terminée",
    failed: "Échouée",
    rejected: "Refusée",
    cancelled: "Annulée",
};


const taskStatusLabels = {
    pending: "En attente",
    waiting_dependency: "Dépendance",
    running: "En cours",
    waiting_approval: "Approbation",
    paused: "En pause",
    completed: "Terminée",
    failed: "Échouée",
    rejected: "Refusée",
    cancelled: "Annulée",
};


const workerLabels = {
    ai_worker: "AI Worker",
    researcher: "Researcher",
    developer: "Developer",
    tester: "Tester",
};


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function formatDate(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "—";
    }

    return new Intl.DateTimeFormat(
        "fr-FR",
        {
            hour: "2-digit",
            minute: "2-digit",
            day: "2-digit",
            month: "2-digit",
        },
    ).format(date);
}


function statusLabel(status) {
    return (
        missionStatusLabels[status]
        || taskStatusLabels[status]
        || status
        || "inconnu"
    );
}


function workerLabel(worker) {
    return (
        workerLabels[worker]
        || worker
        || "Worker"
    );
}


function isActiveMission(mission) {
    return [
        "planning",
        "queued",
        "running",
        "waiting_approval",
        "paused",
    ].includes(mission.status);
}


function progressPercent(mission) {
    const completed =
        mission?.progress?.completed ?? 0;

    const total =
        mission?.progress?.total ?? 0;

    if (!total) {
        return 0;
    }

    return Math.min(
        100,
        Math.max(
            0,
            Math.round(
                (completed / total) * 100,
            ),
        ),
    );
}


async function apiRequest(
    path,
    options = {},
) {
    const response = await fetch(
        path,
        {
            headers: {
                "Content-Type":
                    "application/json; charset=utf-8",
                ...(options.headers || {}),
            },
            ...options,
        },
    );

    let payload = null;

    try {
        payload = await response.json();
    } catch {
        payload = null;
    }

    if (!response.ok) {
        const message =
            payload?.detail
            || payload?.message
            || `Erreur HTTP ${response.status}`;

        throw new Error(message);
    }

    setNetworkState(true);

    return payload;
}


function setNetworkState(online) {
    elements.serverState.classList.toggle(
        "online",
        online,
    );

    elements.serverState.classList.toggle(
        "offline",
        !online,
    );

    elements.serverState.innerHTML = `
        <span class="status-dot"></span>
        ${online ? "Backend connecté" : "Backend hors ligne"}
    `;

    elements.networkBanner.classList.toggle(
        "hidden",
        online,
    );
}


function showToast(
    message,
    type = "",
    duration = 4200,
) {
    const toast =
        document.createElement("div");

    toast.className =
        `toast ${type}`.trim();

    toast.textContent =
        String(message || "");

    elements.toastStack.appendChild(
        toast,
    );

    window.setTimeout(
        () => {
            toast.remove();
        },
        duration,
    );
}


function readStoredChat() {
    try {
        const raw =
            localStorage.getItem(
                CHAT_STORAGE_KEY,
            );

        if (!raw) {
            return [];
        }

        const parsed =
            JSON.parse(raw);

        return Array.isArray(parsed)
            ? parsed
            : [];
    } catch {
        return [];
    }
}


function storeChat(items) {
    try {
        localStorage.setItem(
            CHAT_STORAGE_KEY,
            JSON.stringify(
                items.slice(-100),
            ),
        );
    } catch {
        // L'interface reste fonctionnelle
        // même si le stockage navigateur est indisponible.
    }
}


function chatItemsFromDom() {
    return [
        ...elements.chatMessages
            .querySelectorAll(
                ".message-row[data-role]",
            ),
    ]
        .map(
            (row) => ({
                role:
                    row.dataset.role,

                content:
                    row.dataset.content,

                at:
                    row.dataset.at,
            }),
        )
        .filter(
            (item) =>
                item.content
                && item.role,
        );
}


function scrollChatToBottom() {
    elements.chatMessages.scrollTop =
        elements.chatMessages.scrollHeight;
}


function addChatMessage(
    role,
    content,
    {
        persist = true,
        at = new Date().toISOString(),
    } = {},
) {
    const safeRole = [
        "user",
        "manager",
        "system",
    ].includes(role)
        ? role
        : "system";

    const row =
        document.createElement("div");

    row.className =
        `message-row ${safeRole}`;

    row.dataset.role =
        safeRole;

    row.dataset.content =
        String(content || "");

    row.dataset.at =
        at;

    const label = {
        user: "Toi",
        manager: "Manager",
        system: "Agent-OS",
    }[safeRole];

    row.innerHTML = `
        <div>
            <div class="message-meta">
                ${escapeHtml(label)}
            </div>

            <div class="message-bubble">
                ${escapeHtml(content)}
            </div>
        </div>
    `;

    elements.chatMessages.appendChild(
        row,
    );

    if (persist) {
        storeChat(
            chatItemsFromDom(),
        );
    }

    scrollChatToBottom();
}


function addTypingIndicator() {
    removeTypingIndicator();

    const row =
        document.createElement("div");

    row.id =
        "typingIndicator";

    row.className =
        "message-row manager";

    row.innerHTML = `
        <div>
            <div class="message-meta">
                Manager
            </div>

            <div class="message-bubble typing">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;

    elements.chatMessages.appendChild(
        row,
    );

    scrollChatToBottom();
}


function removeTypingIndicator() {
    document
        .getElementById(
            "typingIndicator",
        )
        ?.remove();
}


function loadChat() {
    const items =
        readStoredChat();

    if (!items.length) {
        addChatMessage(
            "manager",
            (
                "Control Center prêt. "
                + "Tu peux discuter normalement avec moi "
                + "ou me confier une mission."
            ),
            {
                persist: true,
            },
        );

        return;
    }

    for (const item of items) {
        addChatMessage(
            item.role,
            item.content,
            {
                persist: false,
                at: item.at,
            },
        );
    }

    scrollChatToBottom();
}


function renderStats() {
    const dashboard =
        state.dashboard;

    if (!dashboard) {
        return;
    }

    const status =
        dashboard.status || {};

    const agents =
        dashboard.agents || [];

    const approvals =
        dashboard.approvals || [];

    elements.statActiveMissions.textContent =
        status.active_missions ?? 0;

    elements.statBusyAgents.textContent =
        agents.filter(
            (agent) =>
                agent.status === "busy",
        ).length;

    elements.statApprovals.textContent =
        approvals.length;

    elements.statTotalMissions.textContent =
        status.total_missions ?? 0;

    elements.approvalCountBadge.textContent =
        approvals.length;

    elements.versionBadge.textContent =
        `V${status.version || "4.0"}`;
}


function renderAgents() {
    const agents =
        state.dashboard?.agents || [];

    if (!agents.length) {
        elements.agentGrid.innerHTML = `
            <div class="empty-state">
                Aucun worker enregistré.
            </div>
        `;

        return;
    }

    elements.agentGrid.innerHTML =
        agents
            .map(
                (agent) => {
                    const busy =
                        agent.status === "busy";

                    const missions =
                        agent.missions || [];

                    const tasks =
                        agent.running_tasks || [];

                    let meta =
                        "Disponible";

                    if (busy) {
                        const details = [];

                        if (missions.length) {
                            details.push(
                                `Mission ${missions.join(", ")}`,
                            );
                        }

                        if (tasks.length) {
                            details.push(
                                `${tasks.length} tâche(s)`,
                            );
                        }

                        meta =
                            details.join(" · ")
                            || "En exécution";
                    }

                    return `
                        <article class="agent-card ${busy ? "busy" : ""}">
                            <div class="agent-head">
                                <div class="agent-name">
                                    ${escapeHtml(
                                        workerLabel(
                                            agent.name,
                                        ),
                                    )}
                                </div>

                                <div class="agent-state">
                                    <span class="agent-state-dot"></span>
                                    ${busy ? "Occupé" : "Disponible"}
                                </div>
                            </div>

                            <div class="agent-meta">
                                ${escapeHtml(meta)}
                            </div>
                        </article>
                    `;
                },
            )
            .join("");
}


function missionMatchesFilter(
    mission,
) {
    if (state.filter === "all") {
        return true;
    }

    if (state.filter === "active") {
        return isActiveMission(
            mission,
        );
    }

    if (state.filter === "failed") {
        return [
            "failed",
            "rejected",
            "cancelled",
        ].includes(
            mission.status,
        );
    }

    return (
        mission.status
        === state.filter
    );
}


function missionActionButtons(
    mission,
) {
    const buttons = [];

    if ([
        "running",
        "queued",
    ].includes(mission.status)) {
        buttons.push(
            `
                <button
                    type="button"
                    class="mini-action"
                    data-mission-action="pause"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Pause
                </button>
            `,
        );
    }

    if (
        mission.status
        === "paused"
    ) {
        buttons.push(
            `
                <button
                    type="button"
                    class="mini-action"
                    data-mission-action="resume"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Reprendre
                </button>
            `,
        );
    }

    if ([
        "failed",
        "cancelled",
    ].includes(mission.status)) {
        buttons.push(
            `
                <button
                    type="button"
                    class="mini-action"
                    data-mission-action="retry"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Retenter
                </button>
            `,
        );
    }

    if ([
        "planning",
        "queued",
        "running",
        "waiting_approval",
        "paused",
    ].includes(mission.status)) {
        buttons.push(
            `
                <button
                    type="button"
                    class="mini-action danger"
                    data-mission-action="cancel"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Annuler
                </button>
            `,
        );
    }

    return buttons.join("");
}


function renderMissions() {
    const missions = [
        ...(state.dashboard?.missions || []),
    ]
        .sort(
            (a, b) =>
                new Date(
                    b.created_at || 0,
                ).getTime()
                - new Date(
                    a.created_at || 0,
                ).getTime(),
        )
        .filter(
            missionMatchesFilter,
        );

    if (!missions.length) {
        elements.missionList.innerHTML = `
            <div class="empty-state">
                Aucune mission dans ce filtre.
            </div>
        `;

        return;
    }

    elements.missionList.innerHTML =
        missions
            .map(
                (mission) => {
                    const percent =
                        progressPercent(
                            mission,
                        );

                    const completed =
                        mission?.progress?.completed ?? 0;

                    const total =
                        mission?.progress?.total ?? 0;

                    return `
                        <article
                            class="mission-card ${
                                state.selectedMissionId
                                === mission.human_id
                                    ? "selected"
                                    : ""
                            }"
                            data-open-mission="${escapeHtml(mission.human_id)}"
                        >
                            <div class="mission-top">
                                <div class="mission-ref">
                                    ${escapeHtml(mission.human_id)}
                                </div>

                                <span class="status-badge ${escapeHtml(mission.status)}">
                                    ${escapeHtml(
                                        statusLabel(
                                            mission.status,
                                        ),
                                    )}
                                </span>
                            </div>

                            <div class="mission-title">
                                ${escapeHtml(mission.title)}
                            </div>

                            <div class="progress-row">
                                <div class="progress-track">
                                    <div
                                        class="progress-fill"
                                        style="width: ${percent}%"
                                    ></div>
                                </div>

                                <div class="progress-label">
                                    ${completed}/${total}
                                </div>
                            </div>

                            <div class="mission-actions">
                                ${missionActionButtons(mission)}
                            </div>
                        </article>
                    `;
                },
            )
            .join("");
}


function renderApprovals() {
    const approvals =
        state.dashboard?.approvals || [];

    if (!approvals.length) {
        elements.approvalList.innerHTML = `
            <div class="empty-state">
                Aucune approbation en attente.
            </div>
        `;

        return;
    }

    elements.approvalList.innerHTML =
        approvals
            .map(
                (approval) => {
                    const files =
                        approval.files || [];

                    return `
                        <article class="approval-card">
                            <div class="approval-title">
                                ${escapeHtml(approval.mission_id || "Mission")}
                                ·
                                ${escapeHtml(approval.title)}
                            </div>

                            <div class="approval-files">
                                ${
                                    files.length
                                        ? files
                                            .map(
                                                (file) =>
                                                    escapeHtml(file),
                                            )
                                            .join("<br>")
                                        : "Modification protégée"
                                }
                            </div>

                            <div class="approval-actions">
                                <button
                                    type="button"
                                    class="approve-button"
                                    data-approval-action="approve"
                                    data-mission-id="${escapeHtml(approval.mission_id)}"
                                >
                                    Autoriser
                                </button>

                                <button
                                    type="button"
                                    class="reject-button"
                                    data-approval-action="reject"
                                    data-mission-id="${escapeHtml(approval.mission_id)}"
                                >
                                    Refuser
                                </button>
                            </div>
                        </article>
                    `;
                },
            )
            .join("");
}


function renderDashboard() {
    renderStats();
    renderAgents();
    renderMissions();
    renderApprovals();
}


async function refreshDashboard({
    quiet = false,
} = {}) {
    if (state.refreshBusy) {
        return;
    }

    state.refreshBusy = true;

    try {
        const dashboard =
            await apiRequest(
                "/api/dashboard",
            );

        state.dashboard =
            dashboard;

        renderDashboard();

        if (
            state.selectedMissionId
            && elements.missionDrawer
                .classList
                .contains("open")
        ) {
            await refreshMissionDrawer(
                state.selectedMissionId,
                {
                    quiet: true,
                },
            );
        }

        if (!quiet) {
            showToast(
                "Tableau actualisé.",
                "success",
                2200,
            );
        }
    } catch (error) {
        setNetworkState(false);

        if (!quiet) {
            showToast(
                error.message,
                "error",
            );
        }
    } finally {
        state.refreshBusy = false;
    }
}


async function sendChatMessage(
    message,
) {
    if (
        state.chatBusy
        || !message.trim()
    ) {
        return;
    }

    const value =
        message.trim();

    state.chatBusy = true;

    elements.sendButton.disabled =
        true;

    elements.chatInput.disabled =
        true;

    addChatMessage(
        "user",
        value,
    );

    elements.chatInput.value = "";

    resizeComposer();

    addTypingIndicator();

    try {
        const result =
            await apiRequest(
                "/api/chat",
                {
                    method: "POST",
                    body: JSON.stringify({
                        message: value,
                    }),
                },
            );

        removeTypingIndicator();

        if (result.response) {
            addChatMessage(
                "manager",
                result.response,
            );
        }

        await refreshDashboard({
            quiet: true,
        });
    } catch (error) {
        removeTypingIndicator();

        addChatMessage(
            "system",
            `Erreur : ${error.message}`,
        );

        setNetworkState(false);
    } finally {
        state.chatBusy = false;

        elements.sendButton.disabled =
            false;

        elements.chatInput.disabled =
            false;

        elements.chatInput.focus();
    }
}


async function performMissionAction(
    missionId,
    action,
) {
    const key =
        `${missionId}:${action}`;

    if (
        state.actionBusy.has(
            key,
        )
    ) {
        return;
    }

    state.actionBusy.add(
        key,
    );

    try {
        const result =
            await apiRequest(
                `/api/missions/${encodeURIComponent(missionId)}/${action}`,
                {
                    method: "POST",
                },
            );

        showToast(
            result.message
            || `${missionId} mis à jour.`,
            "success",
        );

        addChatMessage(
            "system",
            result.message
            || `${missionId} mis à jour.`,
        );

        await refreshDashboard({
            quiet: true,
        });

        if (
            state.selectedMissionId
            === missionId
        ) {
            await refreshMissionDrawer(
                missionId,
                {
                    quiet: true,
                },
            );
        }
    } catch (error) {
        showToast(
            error.message,
            "error",
        );
    } finally {
        state.actionBusy.delete(
            key,
        );
    }
}


async function performApprovalAction(
    missionId,
    action,
) {
    if (!missionId) {
        return;
    }

    const key =
        `approval:${missionId}:${action}`;

    if (
        state.actionBusy.has(
            key,
        )
    ) {
        return;
    }

    state.actionBusy.add(
        key,
    );

    try {
        const result =
            await apiRequest(
                `/api/approvals/${encodeURIComponent(missionId)}/${action}`,
                {
                    method: "POST",
                },
            );

        const message =
            result.message
            || `${missionId} mis à jour.`;

        showToast(
            message,
            action === "approve"
                ? "success"
                : "",
        );

        addChatMessage(
            "system",
            message,
        );

        await refreshDashboard({
            quiet: true,
        });
    } catch (error) {
        showToast(
            error.message,
            "error",
        );
    } finally {
        state.actionBusy.delete(
            key,
        );
    }
}


function drawerActionButtons(
    mission,
) {
    const buttons = [];

    if ([
        "running",
        "queued",
    ].includes(mission.status)) {
        buttons.push(
            `
                <button
                    class="secondary-button"
                    type="button"
                    data-drawer-action="pause"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Mettre en pause
                </button>
            `,
        );
    }

    if (
        mission.status
        === "paused"
    ) {
        buttons.push(
            `
                <button
                    class="secondary-button"
                    type="button"
                    data-drawer-action="resume"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Reprendre
                </button>
            `,
        );
    }

    if ([
        "failed",
        "cancelled",
    ].includes(mission.status)) {
        buttons.push(
            `
                <button
                    class="secondary-button"
                    type="button"
                    data-drawer-action="retry"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Retenter
                </button>
            `,
        );
    }

    if ([
        "planning",
        "queued",
        "running",
        "waiting_approval",
        "paused",
    ].includes(mission.status)) {
        buttons.push(
            `
                <button
                    class="danger-button"
                    type="button"
                    data-drawer-action="cancel"
                    data-mission-id="${escapeHtml(mission.human_id)}"
                >
                    Annuler la mission
                </button>
            `,
        );
    }

    return buttons.join("");
}


function renderMissionDrawer(
    mission,
) {
    state.selectedMissionId =
        mission.human_id;

    elements.drawerMissionId.textContent =
        mission.human_id;

    elements.drawerTitle.textContent =
        mission.title;

    const completed =
        mission?.progress?.completed ?? 0;

    const total =
        mission?.progress?.total ?? 0;

    const percent =
        progressPercent(
            mission,
        );

    const tasks =
        mission.tasks || [];

    elements.drawerContent.innerHTML = `
        <div class="drawer-summary">
            <div class="mission-top">
                <span class="status-badge ${escapeHtml(mission.status)}">
                    ${escapeHtml(
                        statusLabel(
                            mission.status,
                        ),
                    )}
                </span>

                <span class="progress-label">
                    ${completed}/${total}
                    ·
                    ${formatDate(mission.updated_at)}
                </span>
            </div>

            <div class="drawer-description">
                ${escapeHtml(mission.description)}
            </div>

            <div class="progress-row">
                <div class="progress-track">
                    <div
                        class="progress-fill"
                        style="width: ${percent}%"
                    ></div>
                </div>

                <div class="progress-label">
                    ${percent}%
                </div>
            </div>

            <div class="drawer-actions">
                ${drawerActionButtons(mission)}
            </div>
        </div>

        <div class="task-list">
            ${
                tasks.length
                    ? tasks
                        .map(
                            (task, index) => {
                                const result =
                                    task.error
                                    || task.result
                                    || "";

                                return `
                                    <article class="task-card ${escapeHtml(task.status)}">
                                        <div class="task-head">
                                            <div>
                                                <div class="task-title">
                                                    ${index + 1}.
                                                    ${escapeHtml(task.title)}
                                                </div>

                                                <div class="task-worker">
                                                    ${escapeHtml(
                                                        workerLabel(
                                                            task.worker,
                                                        ),
                                                    )}
                                                </div>
                                            </div>

                                            <span class="status-badge ${escapeHtml(task.status)}">
                                                ${escapeHtml(
                                                    taskStatusLabels[
                                                        task.status
                                                    ]
                                                    || task.status,
                                                )}
                                            </span>
                                        </div>

                                        <div class="task-description">
                                            ${escapeHtml(task.description)}
                                        </div>

                                        ${
                                            result
                                                ? `
                                                    <details class="task-result">
                                                        <summary>
                                                            Voir le résultat
                                                        </summary>

                                                        <pre>${escapeHtml(result)}</pre>
                                                    </details>
                                                `
                                                : ""
                                        }
                                    </article>
                                `;
                            },
                        )
                        .join("")
                    : `
                        <div class="empty-state">
                            Aucune tâche créée pour le moment.
                        </div>
                    `
            }
        </div>
    `;

    elements.missionDrawer.classList.add(
        "open",
    );

    elements.missionDrawer.setAttribute(
        "aria-hidden",
        "false",
    );

    renderMissions();
}


async function openMission(
    missionId,
) {
    state.selectedMissionId =
        missionId;

    renderMissions();

    elements.drawerMissionId.textContent =
        missionId;

    elements.drawerTitle.textContent =
        "Chargement…";

    elements.drawerContent.innerHTML = `
        <div class="empty-state">
            Chargement du détail…
        </div>
    `;

    elements.missionDrawer.classList.add(
        "open",
    );

    elements.missionDrawer.setAttribute(
        "aria-hidden",
        "false",
    );

    await refreshMissionDrawer(
        missionId,
    );
}


async function refreshMissionDrawer(
    missionId,
    {
        quiet = false,
    } = {},
) {
    try {
        const mission =
            await apiRequest(
                `/api/missions/${encodeURIComponent(missionId)}`,
            );

        renderMissionDrawer(
            mission,
        );
    } catch (error) {
        if (!quiet) {
            showToast(
                error.message,
                "error",
            );
        }
    }
}


function closeMissionDrawer() {
    elements.missionDrawer.classList.remove(
        "open",
    );

    elements.missionDrawer.setAttribute(
        "aria-hidden",
        "true",
    );

    state.selectedMissionId =
        null;

    renderMissions();
}


async function pollNotifications() {
    if (state.notificationBusy) {
        return;
    }

    state.notificationBusy = true;

    try {
        const result =
            await apiRequest(
                "/api/notifications",
            );

        const items =
            result.items || [];

        for (const notification of items) {
            addChatMessage(
                "manager",
                notification,
            );

            showToast(
                notification
                    .split("\n")[0],
                "",
                5000,
            );
        }

        if (items.length) {
            await refreshDashboard({
                quiet: true,
            });
        }
    } catch {
        setNetworkState(false);
    } finally {
        state.notificationBusy = false;
    }
}


function resizeComposer() {
    const textarea =
        elements.chatInput;

    textarea.style.height =
        "auto";

    textarea.style.height =
        `${Math.min(
            textarea.scrollHeight,
            150,
        )}px`;
}


elements.chatForm.addEventListener(
    "submit",
    (event) => {
        event.preventDefault();

        sendChatMessage(
            elements.chatInput.value,
        );
    },
);


elements.chatInput.addEventListener(
    "keydown",
    (event) => {
        if (
            event.key === "Enter"
            && !event.shiftKey
        ) {
            event.preventDefault();

            elements.chatForm.requestSubmit();
        }
    },
);


elements.chatInput.addEventListener(
    "input",
    resizeComposer,
);


elements.clearChatButton.addEventListener(
    "click",
    () => {
        elements.chatMessages.innerHTML =
            "";

        storeChat([]);

        addChatMessage(
            "manager",
            (
                "Affichage du chat nettoyé. "
                + "La mémoire Agent-OS n'a pas été supprimée."
            ),
        );
    },
);


elements.refreshButton.addEventListener(
    "click",
    () => {
        refreshDashboard();
    },
);


elements.missionFilters.addEventListener(
    "click",
    (event) => {
        const button =
            event.target.closest(
                "[data-filter]",
            );

        if (!button) {
            return;
        }

        state.filter =
            button.dataset.filter;

        for (
            const chip
            of elements.missionFilters
                .querySelectorAll(
                    "[data-filter]",
                )
        ) {
            chip.classList.toggle(
                "active",
                chip === button,
            );
        }

        renderMissions();
    },
);


elements.missionList.addEventListener(
    "click",
    (event) => {
        const actionButton =
            event.target.closest(
                "[data-mission-action]",
            );

        if (actionButton) {
            event.stopPropagation();

            performMissionAction(
                actionButton.dataset.missionId,
                actionButton.dataset.missionAction,
            );

            return;
        }

        const card =
            event.target.closest(
                "[data-open-mission]",
            );

        if (!card) {
            return;
        }

        openMission(
            card.dataset.openMission,
        );
    },
);


elements.approvalList.addEventListener(
    "click",
    (event) => {
        const button =
            event.target.closest(
                "[data-approval-action]",
            );

        if (!button) {
            return;
        }

        performApprovalAction(
            button.dataset.missionId,
            button.dataset.approvalAction,
        );
    },
);


elements.drawerContent.addEventListener(
    "click",
    (event) => {
        const button =
            event.target.closest(
                "[data-drawer-action]",
            );

        if (!button) {
            return;
        }

        performMissionAction(
            button.dataset.missionId,
            button.dataset.drawerAction,
        );
    },
);


elements.drawerClose.addEventListener(
    "click",
    closeMissionDrawer,
);


elements.drawerBackdrop.addEventListener(
    "click",
    closeMissionDrawer,
);


document.addEventListener(
    "keydown",
    (event) => {
        if (
            event.key === "Escape"
            && elements.missionDrawer
                .classList
                .contains("open")
        ) {
            closeMissionDrawer();
        }
    },
);


async function boot() {
    loadChat();

    resizeComposer();

    await refreshDashboard({
        quiet: true,
    });

    await pollNotifications();

    window.setInterval(
        () => {
            refreshDashboard({
                quiet: true,
            });
        },
        2200,
    );

    window.setInterval(
        pollNotifications,
        1200,
    );

    elements.chatInput.focus();
}


boot();
