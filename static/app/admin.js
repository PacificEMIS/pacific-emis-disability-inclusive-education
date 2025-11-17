// --- Auto-dismiss Bootstrap-style alerts ---
document.querySelectorAll('.alert[data-autohide="true"]').forEach(el => {
  setTimeout(() => el.classList.add('d-none'), 4000);
});

// --- Auto-submit filters (students & staff) ---
(function () {
  const form = document.getElementById('filters');
  if (!form) return;

  const submit = () => (form.requestSubmit ? form.requestSubmit() : form.submit());

  // Debounce helper
  const debounce = (fn, delay) => {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), delay);
    };
  };

  // ❶ Debounce timings
  const debouncedSubmitText   = debounce(submit, 900); // text inputs: ~1s idle
  const debouncedSubmitSelect = debounce(submit, 400); // selects: short pause

  // ❷ Persist focus across reloads so you can keep typing
  const FOCUS_KEY = 'filters:lastFocusId';
  const setFocus = (id) => {
    try { sessionStorage.setItem(FOCUS_KEY, id || ''); } catch {}
  };
  const restoreFocus = () => {
    try {
      const id = sessionStorage.getItem(FOCUS_KEY);
      if (!id) return;
      const el = document.getElementById(id);
      if (el) { el.focus(); el.setSelectionRange?.(el.value.length, el.value.length); }
    } catch {}
  };

  // Restore focus after page load
  document.addEventListener('DOMContentLoaded', restoreFocus);

  // ❸ Wire text inputs (name/email)
  ['q', 'email'].forEach((id) => {
    const input = document.getElementById(id);
    if (!input) return;

    input.addEventListener('focus', () => setFocus(id));
    input.addEventListener('input', () => {
      setFocus(id);            // keep focus target current
      debouncedSubmitText();   // auto-submit after idle; no Enter required
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submit(); // still allow immediate submit
    });
  });

  // ❹ Wire selects (school/year/level/per_page)
  form.querySelectorAll('select').forEach((sel) => {
    sel.addEventListener('focus', () => setFocus(sel.id || sel.name || ''));
    sel.addEventListener('change', () => debouncedSubmitSelect());
  });

  // ❺ Hide any fallback Apply button if present
  const applyBtn = document.getElementById('apply-btn');
  if (applyBtn) applyBtn.style.display = 'none';
})();

