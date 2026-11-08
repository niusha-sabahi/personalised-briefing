/* Describes a briefing for the strip above it: how many sources, how old, and when it was made.
   Pure functions with no DOM access, so they can be tested without a browser. */
(function (root) {
  "use strict";

  /* "April 2025", or "April 2025 to May 2025". Month precision on purpose: some sources are
     dated only to a month, and a day would claim more than is known. */
  function monthRange(dates, locale) {
    const months = [];
    for (const value of dates) {
      const match = /^(\d{4})-(\d{2})/.exec(value || "");
      if (match) {
        months.push(Number(match[1]) * 12 + Number(match[2]) - 1);
      }
    }
    if (months.length === 0) {
      return null;
    }
    const name = function (index) {
      const when = new Date(Date.UTC(Math.floor(index / 12), index % 12, 1));
      return when.toLocaleDateString(locale, { month: "long", year: "numeric", timeZone: "UTC" });
    };
    const first = Math.min.apply(null, months);
    const last = Math.max.apply(null, months);
    return first === last ? name(first) : name(first) + " to " + name(last);
  }

  /* The parts of the strip, in order. Parts that cannot be worked out are left out. */
  function describe(briefing, locale, timeZone) {
    const parts = [];
    const sources = Array.isArray(briefing.sources) ? briefing.sources : [];
    if (sources.length > 0) {
      parts.push(sources.length + (sources.length === 1 ? " source" : " sources"));
    }
    const range = monthRange(sources.map(function (source) { return source.published; }), locale);
    if (range) {
      parts.push("Sources from " + range);
    }
    const made = new Date(briefing.generated_at);
    if (briefing.generated_at && !Number.isNaN(made.getTime())) {
      parts.push(
        "Prepared " +
          made.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short", timeZone: timeZone })
      );
    }
    return parts;
  }

  /* The first letters of the first two words: "Healthcare Policy Analyst" gives "HP". */
  function initials(text) {
    const words = String(text || "").split(/\s+/).filter(Boolean);
    return words.slice(0, 2).map(function (word) { return word[0].toUpperCase(); }).join("");
  }

  /* Which topic labels to show on a card. One hidden label would take the room of the
     "+1 more" chip that replaces it, so it is only hidden from two onwards. */
  function visibleChips(labels, max) {
    if (labels.length <= max + 1) {
      return { shown: labels.slice(), hidden: [] };
    }
    return { shown: labels.slice(0, max), hidden: labels.slice(max) };
  }

  const api = {
    monthRange: monthRange,
    describe: describe,
    initials: initials,
    visibleChips: visibleChips
  };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.BriefingMeta = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
