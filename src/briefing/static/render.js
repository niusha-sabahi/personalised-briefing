/* Turns a briefing's Markdown into HTML that is safe to insert into the page (S8). */
(function (root) {
  "use strict";

  // Only what a briefing needs. No images, styles, forms or scripts, so none can appear
  // even if hostile markup got this far.
  const ALLOWED_TAGS = ["h1", "h2", "h3", "p", "ul", "ol", "li", "a", "strong", "em", "code", "br"];
  const ALLOWED_ATTR = ["href"];
  // Absolute web links only: no javascript:, data: or relative URLs.
  const ALLOWED_URI = /^https?:\/\//i;

  function renderMarkdown(markdown, marked, DOMPurify) {
    if (!DOMPurify.isSupported) {
      // Without a DOM, DOMPurify would hand the input back unchanged. Refuse instead.
      throw new Error("HTML sanitiser is not supported in this environment");
    }
    // Removed first so repeated calls do not stack the same hook.
    DOMPurify.removeHook("afterSanitizeAttributes");
    DOMPurify.addHook("afterSanitizeAttributes", function (node) {
      if (node.tagName === "A") {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    });
    const html = marked.parse(markdown, { async: false, gfm: true });
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: ALLOWED_TAGS,
      ALLOWED_ATTR: ALLOWED_ATTR,
      ALLOWED_URI_REGEXP: ALLOWED_URI,
    });
  }

  const api = { renderMarkdown: renderMarkdown };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.BriefingRender = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
