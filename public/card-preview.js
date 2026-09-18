/*
 * Visualização global de cartas.
 *
 * Qualquer imagem marcada com data-card-image pode ser ampliada sem que cada
 * tela precise implementar seu próprio modal.
 */
(function (global) {
  "use strict";

  let dialog = null;

  function ensureDialog() {
    if (dialog) {
      return dialog;
    }

    dialog = document.createElement("dialog");
    dialog.className = "card-preview-dialog";
    dialog.dataset.cardPreviewDialog = "";
    dialog.innerHTML = `
      <div class="card-preview-shell">
        <button
          type="button"
          class="close card-preview-close"
          aria-label="Fechar ampliação"
        >×</button>
        <img data-card-preview-image alt="">
        <p data-card-preview-label></p>
      </div>
    `;

    document.body.appendChild(dialog);

    dialog.querySelector(".card-preview-close").addEventListener("click", () => {
      dialog.close();
    });

    dialog.addEventListener("click", event => {
      if (event.target === dialog) {
        dialog.close();
      }
    });

    return dialog;
  }

  function open(source, label = "Carta") {
    const imageSource = String(source || "").trim();
    if (!imageSource) {
      return;
    }

    const preview = ensureDialog();
    const image = preview.querySelector("[data-card-preview-image]");
    const caption = preview.querySelector("[data-card-preview-label]");

    image.src = imageSource;
    image.alt = label;
    caption.textContent = label;
    preview.showModal();
  }

  function openFromImage(image) {
    open(
      image.currentSrc || image.src,
      image.dataset.cardLabel || image.alt || "Carta",
    );
  }

  // Capture impede que clicar na arte dentro de um link/botão também navegue.
  document.addEventListener("click", event => {
    const image = event.target.closest?.("img[data-card-image]");
    if (!image) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    openFromImage(image);
  }, true);

  document.addEventListener("keydown", event => {
    const image = event.target.closest?.("img[data-card-image]");
    if (!image || !["Enter", " "].includes(event.key)) {
      return;
    }

    event.preventDefault();
    openFromImage(image);
  });

  global.ManaPonteCardPreview = { open, openFromImage };
}(window));
