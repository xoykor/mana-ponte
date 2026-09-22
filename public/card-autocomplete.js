/*
 * Autocomplete leve de nomes de cartas usando o catálogo já exposto pela API.
 */
(function () {
  "use strict";

  const API_BASE = String(window.MANAPONTE_API_BASE || "")
    .trim()
    .replace(/\/+$/, "");
  const isStaticWithoutApi =
    !API_BASE &&
    (location.hostname.endsWith("github.io") || location.protocol === "file:");

  if (isStaticWithoutApi) {
    return;
  }

  document.querySelectorAll("[data-card-autocomplete]").forEach(input => {
    const listId = input.getAttribute("list");
    const list = listId ? document.getElementById(listId) : null;
    if (!list) {
      return;
    }

    let timer = null;
    let controller = null;

    input.addEventListener("input", () => {
      clearTimeout(timer);
      if (controller) {
        controller.abort();
        controller = null;
      }

      const query = input.value.trim();
      if (query.length < 2) {
        list.innerHTML = "";
        return;
      }

      timer = setTimeout(async () => {
        controller = new AbortController();
        try {
          const base = API_BASE || "";
          const params = new URLSearchParams({
            q: query,
            limit: "30",
          });
          const response = await fetch(`${base}/api/cards?${params}`, {
            credentials: "include",
            signal: controller.signal,
          });
          if (!response.ok) {
            return;
          }

          const payload = await response.json();
          const names = [
            ...new Set(
              (payload.cards || [])
                .map(card => card.printed_name || card.printedName || card.name)
                .filter(Boolean)
            ),
          ].slice(0, 12);

          list.innerHTML = names
            .map(name => {
              const option = document.createElement("option");
              option.value = name;
              return option.outerHTML;
            })
            .join("");
        } catch (error) {
          if (error.name !== "AbortError") {
            list.innerHTML = "";
          }
        } finally {
          controller = null;
        }
      }, 180);
    });
  });
}());
