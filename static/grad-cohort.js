/** Graduation cohort matching — keep in sync with scraper/grad_cohort.py */
(function (global) {
  const SUPPORTED = [2026, 2027, 2028, 2029];
  const INTERNSHIP_CAT = new Set(["Summer Intern", "Fall Co-op / Intern", "Spring Intern"]);

  const CLASS_OF = /class\s+of\s*['\-]?\s*(20)?(\d{2})\b/i;
  const NEW_GRAD_YEAR = /new\s*grad(?:uate)?\s*['\-]?\s*(20)?(\d{2})\b/i;
  const GRAD_APOSTROPHE = /(?:class\s+of|new\s*grad|grad|start|may|spring|fall|summer|january|june)\s*['\-]?(2[4-9])\b/i;
  const FULL_YEAR = /\b(20)(2[4-9])\b/gi;
  const NEW_GRAD_SIGNALS = /\b(new\s*grad|new\s*graduate|university\s+hire|campus\s+hire|campus\s+recruit|college\s+grad|recent\s+grad|entry[-\s]*level|early\s+career|emerging\s+talent|university\s+(software|swe|sde|ml|ai|data|cloud|platform|engineer|developer)|graduate\s+(software|engineer|developer|program|rotation)|rotational\s+(engineer|program|development)|technology\s+development\s+program|associate\s+(software|ml|machine|data|cloud|security|research)\s+engineer|junior\s+(software|engineer|developer)|0\s*[-–]?\s*1\s+years?|0\s+years?\s+(of\s+)?experience|bachelor'?s?\s+(degree\s+)?required|bs\s+in\s+(cs|computer|ece|engineering))\b/i;

  function yearFromGroups(g1, g2) {
    if (g1) return parseInt(g1 + g2, 10);
    const y = parseInt(g2, 10);
    return y < 100 ? 2000 + y : y;
  }

  function extractGradYears(title) {
    if (!title) return new Set();
    const t = String(title).trim();
    const years = new Set();

    let m;
    const re1 = new RegExp(CLASS_OF.source, "gi");
    while ((m = re1.exec(t))) years.add(yearFromGroups(m[1], m[2]));

    const re2 = new RegExp(NEW_GRAD_YEAR.source, "gi");
    while ((m = re2.exec(t))) years.add(yearFromGroups(m[1], m[2]));

    const re3 = new RegExp(GRAD_APOSTROPHE.source, "gi");
    while ((m = re3.exec(t))) years.add(2000 + parseInt(m[1], 10));

    const re4 = new RegExp(FULL_YEAR.source, "gi");
    while ((m = re4.exec(t))) {
      const y = parseInt(m[1] + m[2], 10);
      const start = Math.max(0, m.index - 30);
      const end = Math.min(t.length, m.index + m[0].length + 30);
      const window = t.slice(start, end).toLowerCase();
      if (/grad|class\s+of|university|campus|hire|start|may|spring|fall|summer|january|june|intern/.test(window)) {
        years.add(y);
      }
    }
    return years;
  }

  function isNewGradEligible(title, primaryCategory) {
    const cat = (primaryCategory || "").trim();
    if (cat === "New Grad") return true;
    if (INTERNSHIP_CAT.has(cat)) {
      return /conversion|return\s+offer|full[-\s]*time/i.test(title || "");
    }
    if (["SDE 1", "SDE 2", "AI / ML", "Database", "Infrastructure / DevOps"].includes(cat)) {
      if (NEW_GRAD_SIGNALS.test(title || "")) return true;
      if (/\buniversity\b/i.test(title || "") && !/\bintern\b/i.test(title || "")) return true;
    }
    return NEW_GRAD_SIGNALS.test(title || "");
  }

  function matchesGradCohort(title, targetYear, strict, primaryCategory) {
    if (!SUPPORTED.includes(targetYear)) return true;
    if (!isNewGradEligible(title, primaryCategory)) return false;
    const years = extractGradYears(title);
    if (strict) {
      if (years.has(targetYear)) return true;
      const short = String(targetYear).slice(-2);
      return new RegExp(`['']${short}\\b`, "i").test(title || "");
    }
    if (years.size) return years.has(targetYear);
    return true;
  }

  function matchesJob(job, targetYear, strict) {
    if (!targetYear) return true;
    const y = parseInt(targetYear, 10);
    if (!SUPPORTED.includes(y)) return true;
    const cat = job.primary_category || (job.categories || [])[0] || "";
    return matchesGradCohort(job.title || "", y, !!strict, cat);
  }

  global.GradCohort = {
    SUPPORTED,
    DEFAULT_YEAR: 2027,
    extractGradYears,
    isNewGradEligible,
    matchesGradCohort,
    matchesJob,
  };
})(window);
