const agentSelect = document.getElementById("agent-select");
const sharedToggle = document.getElementById("shared-toggle");
const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");


function addBubble(side, label, content) {

    const bubble = document.createElement("div");
    bubble.className = `bubble ${side}`;

    const labelEl = document.createElement("span");
    labelEl.className = "label";
    labelEl.textContent = label;

    const contentEl = document.createElement("div");
    contentEl.textContent = content;

    bubble.appendChild(labelEl);
    bubble.appendChild(contentEl);

    messagesEl.appendChild(bubble);

    return bubble;
}


function renderHistory(individual, shared) {

    messagesEl.innerHTML = "";

    const isShared = sharedToggle.checked;
    const agentName = agentSelect.value;
    const source = isShared ? shared : individual;

    source.forEach((entry) => {

        const side = entry.role === "user" ? "user" : "agent";

        let label;

        if (isShared) {
            label = entry.agent
                ? (entry.role === "user" ? `Toi → ${entry.agent}` : entry.agent)
                : (side === "user" ? "Toi" : "Agent");
        } else {
            label = side === "user" ? "Toi" : capitalize(agentName);
        }

        addBubble(side, label, entry.content);
    });

    messagesEl.scrollTop = messagesEl.scrollHeight;
}


function capitalize(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
}


async function loadHistory() {

    const agent = agentSelect.value;

    const response = await fetch(`/api/history?agent=${encodeURIComponent(agent)}`);
    const data = await response.json();

    if (data.error) {
        console.error(data.error);
        return;
    }

    renderHistory(data.individual, data.shared);
}


async function sendMessage(message) {

    const agent = agentSelect.value;
    const shared = sharedToggle.checked;

    const pendingBubble = addBubble(
        "agent",
        capitalize(agent),
        "Réflexion en cours..."
    );
    pendingBubble.classList.add("pending");
    messagesEl.scrollTop = messagesEl.scrollHeight;

    sendButton.disabled = true;

    try {

        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent, message, shared })
        });

        const data = await response.json();

        if (data.error) {
            pendingBubble.remove();
            addBubble("agent", "Erreur", data.error);
            return;
        }

        renderHistory(data.individual, data.shared);

    } catch (err) {

        pendingBubble.remove();
        addBubble("agent", "Erreur", "Impossible de contacter le serveur.");
        console.error(err);

    } finally {

        sendButton.disabled = false;
    }
}


form.addEventListener("submit", (event) => {

    event.preventDefault();

    const message = input.value.trim();

    if (!message) {
        return;
    }

    addBubble("user", "Toi", message);
    input.value = "";

    sendMessage(message);
});


input.addEventListener("keydown", (event) => {

    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
    }
});


agentSelect.addEventListener("change", loadHistory);
sharedToggle.addEventListener("change", loadHistory);


loadHistory();