const initOffcanvasMenu = ({ toggle, offcanvas, backdrop, links, close }) => {
  if (!toggle || !offcanvas || !backdrop) {
    return;
  }

  const openMenu = () => {
    offcanvas.classList.add("is-open");
    backdrop.classList.add("is-visible");
    toggle.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
  };

  const closeMenu = () => {
    offcanvas.classList.remove("is-open");
    backdrop.classList.remove("is-visible");
    toggle.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    openMenu();
  });

  close?.addEventListener("click", closeMenu);
  backdrop.addEventListener("click", closeMenu);
  links.forEach((link) => {
    link.addEventListener("click", closeMenu);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && offcanvas.classList.contains("is-open")) {
      closeMenu();
    }
  });
};

document.addEventListener("DOMContentLoaded", () => {
  const mobileNavs = document.querySelectorAll(".mobile-nav");

  if (mobileNavs.length) {
    mobileNavs.forEach((nav) => {
      initOffcanvasMenu({
        toggle: nav.querySelector(".menu-button"),
        offcanvas: nav.querySelector(".offcanvas"),
        close: nav.querySelector(".offcanvas-close"),
        backdrop: nav.querySelector(".offcanvas-backdrop"),
        links: nav.querySelectorAll(".offcanvas-link"),
      });
    });
    return;
  }

  document.querySelectorAll(".menu-button[aria-controls]").forEach((toggle) => {
    const targetId = toggle.getAttribute("aria-controls");
    const offcanvas = targetId ? document.getElementById(targetId) : null;
    const container = toggle.closest("header") || document.body;
    const backdrop =
      offcanvas?.parentElement?.querySelector(".offcanvas-backdrop") ||
      container.querySelector(".offcanvas-backdrop");

    initOffcanvasMenu({
      toggle,
      offcanvas,
      close: offcanvas?.querySelector(".offcanvas-close"),
      backdrop,
      links: offcanvas?.querySelectorAll(".offcanvas-link") || [],
    });
  });
});
