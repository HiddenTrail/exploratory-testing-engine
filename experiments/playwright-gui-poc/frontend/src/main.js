const BACKEND_URL = "http://127.0.0.1:8010";

const responseEl = document.querySelector("#response");

async function ask(choice) {
  responseEl.textContent = "...";
  const res = await fetch(`${BACKEND_URL}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choice }),
  });
  const data = await res.json();
  responseEl.textContent = data.text;
}

document.querySelector("#yes-btn").addEventListener("click", () => ask("yes"));
document.querySelector("#no-btn").addEventListener("click", () => ask("no"));
