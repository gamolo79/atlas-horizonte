document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".mobile-nav").forEach((nav) => {
    const toggle = nav.querySelector(".menu-button");
    const offcanvas = nav.querySelector(".offcanvas");
    const close = nav.querySelector(".offcanvas-close");
    const backdrop = nav.querySelector(".offcanvas-backdrop");

    if (!toggle || !offcanvas || !backdrop) {
      return;
    }

    const openMenu = () => {
      offcanvas.classList.add("is-open");
      backdrop.classList.add("is-visible");
      toggle.setAttribute("aria-expanded", "true");
    };

    const closeMenu = () => {
      offcanvas.classList.remove("is-open");
      backdrop.classList.remove("is-visible");
      toggle.setAttribute("aria-expanded", "false");
    };

    toggle.addEventListener("click", openMenu);
    close?.addEventListener("click", closeMenu);
    backdrop.addEventListener("click", closeMenu);

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeMenu();
      }
    });
  });
});
