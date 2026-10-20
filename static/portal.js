"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const menuButton = document.querySelector(".p-menu-toggle");
  const menu = document.querySelector("#menu-operativo");
  if (menuButton && menu) {
    menuButton.addEventListener("click", () => {
      const expanded = menuButton.getAttribute("aria-expanded") === "true";
      menuButton.setAttribute("aria-expanded", String(!expanded));
      menu.hidden = expanded;
    });
  }
  document.querySelectorAll("[data-print]").forEach(button => {
    button.addEventListener("click", () => window.print());
  });
  document.querySelectorAll("form[data-confirm]").forEach(form => {
    form.addEventListener("submit", event => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
});
