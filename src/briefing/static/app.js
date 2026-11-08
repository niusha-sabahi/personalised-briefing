/* The briefing page: pick a persona, fetch its briefing, show it. */
(function () {
  "use strict";

  // The first briefing embeds every recent source and then calls the model, so it is slow.
  // This is longer than the server's own OpenAI timeout and retries.
  const REQUEST_TIMEOUT_MS = 240000;

  const personasEl = document.getElementById("personas");
  const statusEl = document.getElementById("status");
  const briefingEl = document.getElementById("briefing");

  let latestRequest = 0;

  async function getJson(url) {
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, { signal: controller.signal });
      let body = null;
      try {
        body = await response.json();
      } catch (_) {
        // Not JSON: fall through to the generic message below.
      }
      if (!response.ok) {
        const detail = body && typeof body.detail === "string" ? body.detail : null;
        throw new Error(detail || "The server returned an error (" + response.status + ").");
      }
      return body;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("The request took too long. Try again.");
      }
      if (error instanceof TypeError) {
        throw new Error("Could not reach the server.");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function setStatus(message, retry) {
    // Text only, never HTML: messages can come from the server.
    statusEl.textContent = message;
    if (retry) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "retry";
      button.textContent = "Try again";
      button.addEventListener("click", retry);
      statusEl.append(" ", button);
    }
  }

  async function showBriefing(persona, button) {
    const request = ++latestRequest;
    for (const other of personasEl.children) {
      other.setAttribute("aria-pressed", String(other === button));
    }
    briefingEl.replaceChildren();
    briefingEl.setAttribute("aria-busy", "true");
    setStatus("Preparing the briefing for " + persona.position + "… the first one can take a minute.");
    try {
      const briefing = await getJson("/briefings/" + encodeURIComponent(persona.id) + "?format=json");
      if (request !== latestRequest) {
        return; // A newer choice replaced this one.
      }
      briefingEl.innerHTML = window.BriefingRender.renderMarkdown(
        briefing.markdown, window.marked, window.DOMPurify
      );
      setStatus("");
      briefingEl.focus();
    } catch (error) {
      if (request !== latestRequest) {
        return;
      }
      setStatus(error.message, function () { showBriefing(persona, button); });
    } finally {
      if (request === latestRequest) {
        briefingEl.setAttribute("aria-busy", "false");
      }
    }
  }

  async function init() {
    try {
      const personas = await getJson("/personas");
      for (const persona of personas) {
        const button = document.createElement("button");
        button.type = "button";
        button.setAttribute("aria-pressed", "false");
        button.textContent = persona.position + " · " + persona.location;
        button.addEventListener("click", function () { showBriefing(persona, button); });
        personasEl.append(button);
      }
    } catch (error) {
      setStatus(error.message, init);
    }
  }

  init();
})();
