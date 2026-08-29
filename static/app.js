let chats = [];
let currentChatId = null;


// ============================================================
// DOM
// ============================================================

const chatList =
    document.getElementById("chatList");

const messages =
    document.getElementById("messages");

const chatTitle =
    document.getElementById("chatTitle");

const chatAgents =
    document.getElementById("chatAgents");

const messageInput =
    document.getElementById("messageInput");

const sendButton =
    document.getElementById("sendButton");

const newChatButton =
    document.getElementById("newChatButton");

const newChatModal =
    document.getElementById("newChatModal");

const closeModalButton =
    document.getElementById("closeModalButton");

const cancelChatButton =
    document.getElementById("cancelChatButton");

const createChatButton =
    document.getElementById("createChatButton");


// ============================================================
// AGENTS
// ============================================================

const AGENT_LABELS = {

    planner: "🧠 Planner",

    developer: "💻 Developer",

    tester: "🧪 Tester",

    researcher: "🌐 Researcher"

};


// ============================================================
// INITIALISATION
// ============================================================

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        await loadChats();

        setupEvents();

    }
);


// ============================================================
// EVENTS
// ============================================================

function setupEvents() {

    newChatButton.addEventListener(
        "click",
        openNewChatModal
    );

    closeModalButton.addEventListener(
        "click",
        closeNewChatModal
    );

    cancelChatButton.addEventListener(
        "click",
        closeNewChatModal
    );

    createChatButton.addEventListener(
        "click",
        createNewChat
    );

    sendButton.addEventListener(
        "click",
        sendMessage
    );

    messageInput.addEventListener(
        "keydown",
        event => {

            if (
                event.key === "Enter"
                && !event.shiftKey
            ) {

                event.preventDefault();

                sendMessage();

            }

        }
    );


    // --------------------------------------------------------
    // RESET MÉMOIRES
    // --------------------------------------------------------

    document
        .querySelectorAll(".memory-button")
        .forEach(button => {

            button.addEventListener(
                "click",
                async () => {

                    const memoryType =
                        button.dataset.memory;

                    await resetMemory(
                        memoryType
                    );

                }

            );

        });

}


// ============================================================
// CHARGER LES CHATS
// ============================================================

async function loadChats() {

    const response =
        await fetch("/api/chats");

    const data =
        await response.json();

    chats =
        data.chats || [];

    renderChatList();

}


// ============================================================
// AFFICHER LISTE CHATS
// ============================================================

function renderChatList() {

    chatList.innerHTML = "";

    if (!chats.length) {

        chatList.innerHTML = `
            <div class="empty-chats">
                Aucun chat
            </div>
        `;

        return;

    }


    chats.forEach(chat => {

        const item =
            document.createElement("div");

        item.className =
            "chat-item";


        if (
            chat.id === currentChatId
        ) {

            item.classList.add(
                "active"
            );

        }


        const agents =
            (chat.agents || [])
                .map(
                    agent =>
                        AGENT_LABELS[agent]
                        || agent
                )
                .join(" · ");


        item.innerHTML = `

            <div class="chat-item-main">

                <div class="chat-item-title">

                    ${escapeHtml(
                        chat.title
                        || "Nouveau chat"
                    )}

                </div>

                <div class="chat-item-agents">

                    ${escapeHtml(
                        agents
                    )}

                </div>

            </div>

            <button
                class="delete-chat-button"
                title="Supprimer le chat"
            >
                ×
            </button>

        `;


        item
            .querySelector(
                ".chat-item-main"
            )
            .addEventListener(
                "click",
                () => {

                    loadChat(
                        chat.id
                    );

                }
            );


        item
            .querySelector(
                ".delete-chat-button"
            )
            .addEventListener(
                "click",
                event => {

                    event.stopPropagation();

                    deleteChat(
                        chat.id
                    );

                }
            );


        chatList.appendChild(
            item
        );

    });

}


// ============================================================
// CHARGER UN CHAT
// ============================================================

async function loadChat(chatId) {

    const response =
        await fetch(
            `/api/chats/${chatId}`
        );

    if (!response.ok) {

        return;

    }

    const data =
        await response.json();

    const chat =
        data.chat;

    currentChatId =
        chat.id;

    renderChat(
        chat
    );

    renderChatList();

}


// ============================================================
// AFFICHER UN CHAT
// ============================================================

function renderChat(chat) {

    chatTitle.textContent =
        chat.title
        || "Nouveau chat";


    chatAgents.innerHTML =
        "";


    (chat.agents || [])
        .forEach(agent => {

            const badge =
                document.createElement(
                    "span"
                );

            badge.className =
                "agent-badge";

            badge.textContent =
                AGENT_LABELS[agent]
                || agent;

            chatAgents.appendChild(
                badge
            );

        });


    messages.innerHTML =
        "";


    const chatMessages =
        chat.messages || [];


    if (!chatMessages.length) {

        messages.innerHTML = `

            <div class="welcome">

                <h2>
                    Nouveau chat
                </h2>

                <p>
                    ${escapeHtml(
                        (chat.agents || [])
                            .map(
                                agent =>
                                    AGENT_LABELS[agent]
                                    || agent
                            )
                            .join(" · ")
                    )}
                </p>

            </div>

        `;

        return;

    }


    chatMessages.forEach(
        message => {

            renderMessage(
                message
            );

        }
    );


    scrollToBottom();

}


// ============================================================
// AFFICHER MESSAGE
// ============================================================

function renderMessage(message) {

    const wrapper =
        document.createElement(
            "div"
        );


    wrapper.className =
        "message " +
        (
            message.role === "user"
                ? "user-message"
                : "agent-message"
        );


    if (
        message.role === "agent"
    ) {

        const agentName =
            AGENT_LABELS[
                message.agent
            ]
            || message.agent
            || "Agent";


        wrapper.innerHTML = `

            <div class="message-agent">

                ${escapeHtml(
                    agentName
                )}

            </div>

            <div class="message-content">

                ${formatMessage(
                    message.content
                    || ""
                )}

            </div>

        `;

    }

    else {

        wrapper.innerHTML = `

            <div class="message-content">

                ${formatMessage(
                    message.content
                    || ""
                )}

            </div>

        `;

    }


    messages.appendChild(
        wrapper
    );

}


// ============================================================
// ENVOYER MESSAGE
// ============================================================

async function sendMessage() {

    const message =
        messageInput.value.trim();


    if (!message) {

        return;

    }


    if (!currentChatId) {

        alert(
            "Sélectionne ou crée un chat."
        );

        return;

    }


    messageInput.value = "";

    sendButton.disabled =
        true;


    // --------------------------------------------------------
    // Message utilisateur immédiat
    // --------------------------------------------------------

    renderMessage({

        role:
            "user",

        content:
            message

    });


    scrollToBottom();


    try {

        const response =
            await fetch(
                "/api/chat",
                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            chat_id:
                                currentChatId,

                            message:
                                message

                        })

                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.error
                || "Erreur."
            );

            return;

        }


        // ----------------------------------------------------
        // Recharger le chat
        // ----------------------------------------------------

        renderChat(
            data.chat
        );


        await loadChats();

    }

    catch (error) {

        console.error(
            error
        );

        alert(
            "Erreur de communication avec Agent-OS."
        );

    }

    finally {

        sendButton.disabled =
            false;

        messageInput.focus();

    }

}


// ============================================================
// NOUVEAU CHAT
// ============================================================

function openNewChatModal() {

    newChatModal.classList.remove(
        "hidden"
    );

}


function closeNewChatModal() {

    newChatModal.classList.add(
        "hidden"
    );

}


// ============================================================
// CRÉER CHAT
// ============================================================

async function createNewChat() {

    const selectedAgents =
        Array.from(
            document.querySelectorAll(
                "#agentSelector input:checked"
            )
        )
        .map(
            checkbox =>
                checkbox.value
        );


    if (!selectedAgents.length) {

        alert(
            "Sélectionne au moins un agent."
        );

        return;

    }


    createChatButton.disabled =
        true;


    try {

        const response =
            await fetch(
                "/api/chats",
                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            agents:
                                selectedAgents

                        })

                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.error
                || "Impossible de créer le chat."
            );

            return;

        }


        // ----------------------------------------------------
        // Décocher les agents
        // ----------------------------------------------------

        document
            .querySelectorAll(
                "#agentSelector input"
            )
            .forEach(
                checkbox => {

                    checkbox.checked =
                        false;

                }
            );


        closeNewChatModal();


        await loadChats();


        await loadChat(
            data.chat.id
        );

    }

    catch (error) {

        console.error(
            error
        );

        alert(
            "Erreur lors de la création du chat."
        );

    }

    finally {

        createChatButton.disabled =
            false;

    }

}


// ============================================================
// SUPPRIMER CHAT
// ============================================================

async function deleteChat(chatId) {

    const confirmed =
        confirm(
            "Supprimer ce chat ?"
        );


    if (!confirmed) {

        return;

    }


    const response =
        await fetch(
            `/api/chats/${chatId}`,
            {

                method:
                    "DELETE"

            }
        );


    if (!response.ok) {

        alert(
            "Impossible de supprimer le chat."
        );

        return;

    }


    if (
        currentChatId === chatId
    ) {

        currentChatId =
            null;

        chatTitle.textContent =
            "Aucun chat";

        chatAgents.innerHTML =
            "";

        messages.innerHTML = `

            <div class="welcome">

                <h2>
                    Agent-OS
                </h2>

                <p>
                    Crée un nouveau chat.
                </p>

            </div>

        `;

    }


    await loadChats();

}


// ============================================================
// RESET MÉMOIRE
// ============================================================

async function resetMemory(
    memoryType
) {

    const labels = {

        planner:
            "Planner",

        developer:
            "Developer",

        tester:
            "Tester",

        researcher:
            "Researcher",

        shared:
            "mémoire partagée"

    };


    const label =
        labels[memoryType]
        || memoryType;


    const confirmed =
        confirm(
            `Réinitialiser la ${label} ?`
        );


    if (!confirmed) {

        return;

    }


    try {

        const response =
            await fetch(
                "/api/reset-memory",
                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            type:
                                memoryType

                        })

                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.error
                || "Erreur."
            );

            return;

        }


        alert(
            data.message
        );

    }

    catch (error) {

        console.error(
            error
        );

        alert(
            "Erreur lors du reset."
        );

    }

}


// ============================================================
// FORMATAGE MESSAGE
// ============================================================

function formatMessage(text) {

    return escapeHtml(
        text
    )
    .replace(
        /\*\*(.*?)\*\*/g,
        "<strong>$1</strong>"
    )
    .replace(
        /\n/g,
        "<br>"
    );

}


// ============================================================
// ESCAPE HTML
// ============================================================

function escapeHtml(text) {

    const div =
        document.createElement(
            "div"
        );

    div.textContent =
        text;

    return div.innerHTML;

}


// ============================================================
// SCROLL
// ============================================================

function scrollToBottom() {

    messages.scrollTop =
        messages.scrollHeight;

}