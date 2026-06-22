const form = document.getElementById("chat-form");
const input = document.getElementById("query-input");
const messages = document.getElementById("messages");
const status = document.getElementById("status");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = input.value.trim();
  if (!query) return;

  addMessage(query, "user");
  input.value = "";
  setLoading(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    addMessage(data.response, "bot", data.sources || []);
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
}

function setLoading(loading) {
  const btn = form.querySelector("button");
  btn.disabled = loading;
  btn.textContent = loading ? "Thinking..." : "Send";
  status.textContent = loading ? "Consulting the READMEs..." : "";
}
