/* Public navigation progressively enhances a complete, usable HTML menu. */
(() => {
  "use strict";
  const toggle = document.querySelector(".fp-menu-toggle");
  const navigation = document.getElementById("financeplus-navigation");
  const header = document.querySelector(".fp-header");
  const main = document.querySelector("main");
  if (main && !main.id) main.id = "main-content";
  if (!toggle || !navigation || !header) return;
  const compact = window.matchMedia("(max-width: 1080px)");
  const setOpen = (open) => {
    const active = compact.matches && open;
    toggle.setAttribute("aria-expanded", String(active));
    navigation.hidden = compact.matches && !active;
    header.classList.toggle("fp-menu-open", active);
  };
  const resize = () => {
    toggle.hidden = !compact.matches;
    setOpen(false);
  };
  toggle.addEventListener("click", () => {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });
  header.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false);
      toggle.focus();
    }
  });
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) setOpen(false);
  });
  if (compact.addEventListener) compact.addEventListener("change", resize);
  else compact.addListener(resize);
  resize();
})();
