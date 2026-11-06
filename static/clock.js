"use strict";

function setCurrentTime() {
    const now = new Date();

    const hours = String(now.getHours()).padStart(2, "0");
    const minutes = String(now.getMinutes()).padStart(2, "0");

    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");

    document.getElementById("currtime").value = `${hours}:${minutes}`;
    document.getElementById("selected_date").value = `${year}-${month}-${day}`;
}

// Default the date field to the user's local calendar date on page load.
document.addEventListener("DOMContentLoaded", function () {
    const dateInput = document.getElementById("selected_date");

    if (dateInput && !dateInput.value) {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");

        dateInput.value = `${year}-${month}-${day}`;
    }
});
