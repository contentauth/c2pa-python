document.addEventListener("DOMContentLoaded", () => {
  const selector = document.getElementById("docs-version");
  if (selector) {
    selector.addEventListener("change", () => {
      window.location.assign(selector.value);
    });
  }
});
