/* The briefing page: pick a persona, fetch its briefing, show it. */
(function () {
  "use strict";

  // The first briefing embeds every recent source and then calls the model, so it is slow.
  // This is longer than the server's own OpenAI timeout and retries.
  const REQUEST_TIMEOUT_MS = 240000;

  // More topic chips than this are folded into a "+n more" chip, to keep the cards tidy.
  const MAX_CHIPS = 4;

  const personasEl = document.getElementById("personas");
  const statusEl = document.getElementById("status");
  const metaEl = document.getElementById("meta");
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

  function setStatus(message, retry, busy) {
    // Text only, never HTML: messages can come from the server.
    statusEl.textContent = message;
    statusEl.classList.toggle("loading", Boolean(busy));
    if (retry) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "retry";
      button.textContent = "Try again";
      button.addEventListener("click", retry);
      statusEl.append(" ", button);
    }
  }

  function showMeta(briefing) {
    // Text only: each part is a span with textContent.
    const parts = window.BriefingMeta.describe(briefing);
    metaEl.replaceChildren(...parts.map(function (part) {
      const item = document.createElement("span");
      item.textContent = part;
      return item;
    }));
    metaEl.hidden = parts.length === 0;
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    return node;
  }

  function decorative(node) {
    node.setAttribute("aria-hidden", "true");
    return node;
  }

  function personaCard(persona, topicLabels) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", "false");
    button.tabIndex = -1; // Only one card is a tab stop at a time; the arrow keys move between them.

    const labels = persona.topic_ids.map(function (id) { return topicLabels.get(id) || id; });
    const view = window.BriefingMeta.visibleChips(labels, MAX_CHIPS);
    const chips = element("span", "chips", "");
    for (const label of view.shown) {
      chips.append(element("span", "chip", label));
    }
    if (view.hidden.length > 0) {
      const more = element("span", "chip", "+" + view.hidden.length + " more");
      more.title = view.hidden.join(", ");
      chips.append(more);
    }

    const text = element("span", "persona-text", "");
    text.append(
      element("span", "persona-name", persona.position),
      element("span", "persona-place", persona.location),
      chips
    );
    button.append(
      decorative(element("span", "badge", window.BriefingMeta.initials(persona.position))),
      text,
      decorative(element("span", "check", ""))
    );
    return button;
  }

  /* Arrow keys move between the cards and Home and End jump to the ends, as in a radio group.
     They only move focus: choosing a persona starts a briefing, which can cost a model call,
     so that takes Enter, Space or a click. */
  function moveFocus(event) {
    const cards = Array.from(personasEl.children);
    const index = cards.indexOf(document.activeElement);
    if (index < 0) {
      return;
    }
    const last = cards.length - 1;
    const targets = {
      ArrowRight: (index + 1) % cards.length,
      ArrowDown: (index + 1) % cards.length,
      ArrowLeft: (index + last) % cards.length,
      ArrowUp: (index + last) % cards.length,
      Home: 0,
      End: last
    };
    if (!(event.key in targets)) {
      return;
    }
    event.preventDefault();
    const target = cards[targets[event.key]];
    for (const card of cards) {
      card.tabIndex = card === target ? 0 : -1;
    }
    target.focus();
  }

  async function showBriefing(persona, button) {
    const request = ++latestRequest;
    for (const other of personasEl.children) {
      other.setAttribute("aria-checked", String(other === button));
      other.tabIndex = other === button ? 0 : -1;
    }
    briefingEl.replaceChildren();
    metaEl.hidden = true;
    briefingEl.setAttribute("aria-busy", "true");
    setStatus(
      "Preparing the briefing for " + persona.position + ". The first one usually takes 10 to 20 seconds.",
      null,
      true
    );
    try {
      const briefing = await getJson("/briefings/" + encodeURIComponent(persona.id) + "?format=json");
      if (request !== latestRequest) {
        return; // A newer choice replaced this one.
      }
      briefingEl.innerHTML = window.BriefingRender.renderMarkdown(
        briefing.markdown, window.marked, window.DOMPurify
      );
      showMeta(briefing);
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
      const [personas, topics] = await Promise.all([getJson("/personas"), getJson("/topics")]);
      const topicLabels = new Map(topics.map(function (topic) { return [topic.id, topic.label]; }));
      for (const persona of personas) {
        const button = personaCard(persona, topicLabels);
        button.addEventListener("click", function () { showBriefing(persona, button); });
        personasEl.append(button);
      }
      if (personasEl.firstElementChild) {
        personasEl.firstElementChild.tabIndex = 0; // Somewhere to tab to before a choice is made.
      }
      personasEl.addEventListener("keydown", moveFocus);
    } catch (error) {
      setStatus(error.message, init);
    }
  }

  init();
})();
