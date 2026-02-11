/* Fochs WebSocket Chat Client */
(function () {
    "use strict";

    const messagesEl = document.getElementById("chat-messages");
    const inputEl = document.getElementById("chat-input");
    const formEl = document.getElementById("chat-form");
    const statusEl = document.getElementById("connection-status");
    const sendBtn = document.getElementById("send-btn");

    let ws = null;
    let reconnectDelay = 1000;

    function setStatus(text, cls) {
        statusEl.textContent = text;
        statusEl.className = "connection-status " + cls;
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function addMessage(content, cls) {
        const div = document.createElement("div");
        div.className = "chat-msg " + cls;
        div.textContent = content;
        messagesEl.appendChild(div);
        scrollToBottom();
        return div;
    }

    function connect() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = proto + "//" + location.host + "/ws/chat";
        setStatus("Verbinde...", "connecting");

        ws = new WebSocket(url);

        ws.onopen = function () {
            setStatus("Verbunden", "connected");
            reconnectDelay = 1000;
            sendBtn.disabled = false;
        };

        ws.onclose = function () {
            setStatus("Getrennt - verbinde erneut...", "disconnected");
            sendBtn.disabled = true;
            setTimeout(connect, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 2, 15000);
        };

        ws.onerror = function () {
            setStatus("Verbindungsfehler", "disconnected");
        };

        ws.onmessage = function (evt) {
            let data;
            try {
                data = JSON.parse(evt.data);
            } catch (e) {
                return;
            }

            switch (data.type) {
                case "thinking":
                    if (data.content) {
                        addMessage(data.content, "thinking");
                    }
                    break;

                case "tool_call":
                    addMessage("Tool: " + data.tool, "tool");
                    break;

                case "tool_result":
                    addMessage(data.output || "(kein Ergebnis)", "tool");
                    break;

                case "response":
                    addMessage(data.content, "assistant");
                    break;

                case "error":
                    addMessage(data.message || "Fehler", "error");
                    break;

                case "done":
                    sendBtn.disabled = false;
                    inputEl.disabled = false;
                    inputEl.focus();
                    break;
            }
        };
    }

    formEl.addEventListener("submit", function (e) {
        e.preventDefault();
        const text = inputEl.value.trim();
        if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

        addMessage(text, "user");
        ws.send(JSON.stringify({ message: text }));
        inputEl.value = "";
        sendBtn.disabled = true;
        inputEl.disabled = true;
    });

    connect();
})();
