// Medical Store Pro - Main JavaScript File

// Confirm before deleting/removing items
const deleteButtons = document.querySelectorAll("[data-confirm]");
deleteButtons.forEach((button) => {
  button.addEventListener("click", function (e) {
    if (!confirm("Are you sure you want to proceed?")) {
      e.preventDefault();
    }
  });
});

// Validate quantity inputs
const qtyInputs = document.querySelectorAll('input[type="number"]');
qtyInputs.forEach((input) => {
  input.addEventListener("input", function () {
    const min = parseInt(this.min) || 0;
    const max = parseInt(this.max) || Infinity;
    let value = parseInt(this.value) || 0;

    if (value < min) this.value = min;
    if (value > max) this.value = max;
  });
});

// Set active sidebar link
const currentPath = window.location.pathname;
const sidebarLinks = document.querySelectorAll(".sidebar-link");

sidebarLinks.forEach((link) => {
  if (link.getAttribute("href") === currentPath) {
    link.classList.add(
      "bg-primary",
      "text-white",
      "shadow-lg",
      "hover:bg-primary",
      "hover:text-white",
    );
    link.classList.remove("text-white/70");
  }
});
