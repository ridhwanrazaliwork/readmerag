const form = document.getElementById("chat-form");
const input = document.getElementById("query-input");
const messages = document.getElementById("messages");
const status = document.getElementById("status");
const chatHistory = [];

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = input.value.trim();
  if (!query) return;

  addMessage(query, "user");
  input.value = "";
  setLoading(true);

  const last10 = chatHistory.slice(-10);

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, history: last10 }),
    });
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    const msgEl = addMessage("", "bot");
    let fullResponse = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const line of value.split("\n")) {
        if (line.startsWith("data: ")) {
          const payload = line.slice(6);
          if (payload === "[DONE]") break;
          const parsed = JSON.parse(payload);
          if (parsed.type === "sources") {
            const srcDiv = document.createElement("div");
            srcDiv.className = "sources";
            srcDiv.textContent = "Sources: " + parsed.sources.map((s) => s.repo).join(", ");
            msgEl.appendChild(srcDiv);
          } else if (parsed.type === "token") {
            msgEl.insertAdjacentText("beforeend", parsed.token);
            messages.scrollTop = messages.scrollHeight;
            fullResponse += parsed.token;
          }
        }
      }
    }
    chatHistory.push({ role: "user", content: query });
    chatHistory.push({ role: "assistant", content: fullResponse });
  } catch {
    addMessage("Network error. Please try again.", "bot");
  } finally {
    setLoading(false);
    input.focus();
  }
});

function addMessage(text, role, sources = []) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.textContent = text;

  if (sources.length > 0) {
    const srcDiv = document.createElement("div");
    srcDiv.className = "sources";
    srcDiv.textContent = "Sources: " + sources.map((s) => s.repo).join(", ");
    el.appendChild(srcDiv);
  }

  messages.appendChild(el);
  el.scrollIntoView({ behavior: "smooth" });
  return el;
}

function setLoading(loading) {
  const btn = form.querySelector("button");
  btn.disabled = loading;
  btn.textContent = loading ? "Thinking..." : "Send";
  status.textContent = loading ? "Consulting the READMEs..." : "";
}
