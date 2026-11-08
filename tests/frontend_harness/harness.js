/* Test page: renders the Markdown cases given in ?cases=<JSON list> with the real page code,
   and writes the results as JSON into #out for the Python test to read. Not shipped.
   With &unsafe=1 it skips the sanitiser, as a negative control for the tests. */
(function () {
  "use strict";
  const out = document.getElementById("out");
  try {
    const params = new URLSearchParams(location.search);
    const cases = JSON.parse(params.get("cases"));
    const unsafe = params.has("unsafe");
    const results = cases.map(function (markdown) {
      if (unsafe) {
        return window.marked.parse(markdown, { async: false, gfm: true });
      }
      return window.BriefingRender.renderMarkdown(markdown, window.marked, window.DOMPurify);
    });
    out.textContent = JSON.stringify({ results: results });
  } catch (error) {
    out.textContent = JSON.stringify({ error: String(error) });
  }
})();
