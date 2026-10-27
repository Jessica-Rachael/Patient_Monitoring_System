/* Show / hide a device key */
function toggleSecret(btn) {
  const el = btn.parentElement.querySelector(".secret");
  const hidden = el.textContent.startsWith("•");
  el.textContent = hidden ? el.dataset.secret : "••••••••••••••••";
  btn.textContent = hidden ? "Hide" : "Show";
}
