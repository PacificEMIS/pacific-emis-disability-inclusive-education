(function () {

  // --- simple dependency map ------------------------------------
  // child CFT code -> { parentCode, parentValue }
  // parentValue is the actual <option value="..."> for the “Yes” / trigger answer
  const CFT_DEPENDENCIES = {
    CFT2: { parentCode: "CFT1", parentValue: "1" }, // CFT2 only if CFT1 == Yes(1)
    // add more as needed:
    CFT5: { parentCode: "CFT4", parentValue: "1" },
    CFT9: { parentCode: "CFT7", parentValue: "1" },
  };

  function initCftDomainTabs() {
    // Map CFT codes to functional domains
    const CATEGORY_MAP = {
      CFT1: "visual",
      CFT2: "visual",
      CFT3: "visual",

      CFT4: "hearing",
      CFT5: "hearing",
      CFT6: "hearing",

      CFT7: "physical",
      CFT8: "physical",
      CFT9: "physical",
      CFT10: "physical",
      CFT11: "physical",

      CFT12: "communication",

      CFT13: "learning",
      CFT14: "learning",
      CFT15: "learning",
      CFT16: "learning",

      CFT17: "behaviour",
      CFT18: "behaviour",

      CFT19: "emotional",
      CFT20: "emotional",
    };

    const questions = document.querySelectorAll(".cft-question");
    const navButtons = document.querySelectorAll(".cft-domain");

    if (!questions.length || !navButtons.length) return;

    // Tag each question with its domain
    questions.forEach((el) => {
      const code = (el.dataset.cftCode || "").toUpperCase();
      const category = CATEGORY_MAP[code] || "other";
      el.dataset.cftCategory = category;
    });

    function showOnly(category) {
      questions.forEach((q) => {
        q.classList.toggle("d-none", q.dataset.cftCategory !== category);
      });
    }

    function hideAll() {
      questions.forEach((q) => q.classList.add("d-none"));
    }

    // Start with no domain selected — all hidden
    hideAll();
    let activeCategory = null;

    navButtons.forEach((btn) => {
      btn.addEventListener("click", function () {
        const selected = this.dataset.cftFilter;

        // Clicking the active button again clears the filter
        if (activeCategory === selected) {
          activeCategory = null;
          navButtons.forEach((b) => b.classList.remove("active"));
          hideAll();
          return;
        }

        activeCategory = selected;

        navButtons.forEach((b) => b.classList.remove("active"));
        this.classList.add("active");

        showOnly(selected);

        // On small screens, scroll the questions into view
        if (window.innerWidth < 768) {
          const container = document.getElementById("cft-questions");
          if (container) {
            container.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        }
      });
    });
  }

  // --- decision-tree / skip logic -------------------------------
  function initCftDependencies() {
    Object.entries(CFT_DEPENDENCIES).forEach(([childCode, cfg]) => {
      const childEl = document.querySelector(
        `.cft-question[data-cft-code="${childCode}"]`
      );
      const parentEl = document.querySelector(
        `.cft-question[data-cft-code="${cfg.parentCode}"]`
      );

      if (!childEl || !parentEl) return;

      // Assume the parent question uses a <select>
      const parentSelect = parentEl.querySelector("select");
      if (!parentSelect) return;

      function updateChildVisibility() {
        const shouldShow = parentSelect.value === String(cfg.parentValue);
        // We use the "hidden" attribute so this stacks cleanly
        // with the domain tabs' .d-none class.
        childEl.hidden = !shouldShow;
      }

      parentSelect.addEventListener("change", updateChildVisibility);
      // Initial state when the page loads (important for edit form)
      updateChildVisibility();
    });
  }

  // Run after DOM is ready
  function init() {
    initCftDomainTabs();
    initCftDependencies();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
