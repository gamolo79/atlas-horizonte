document.querySelectorAll('[data-share]')?.forEach((button) => {
  button.addEventListener('click', () => {
    const url = button.getAttribute('data-share');
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url);
      button.textContent = 'Enlace copiado';
      setTimeout(() => {
        button.textContent = 'Copiar enlace';
      }, 2000);
    }
  });
});
