// Placeholder for future interactions (filters, toasts, etc.).
// Example: Auto-dismiss alerts
document.querySelectorAll('.alert[data-autohide="true"]').forEach(el => {
  setTimeout(() => el.classList.add('d-none'), 4000);
});
