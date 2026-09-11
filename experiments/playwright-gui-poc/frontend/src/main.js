const BACKEND_URL = "http://127.0.0.1:8010";

const pages = {
  question: document.querySelector("#question-page"),
  yes: document.querySelector("#yes-page"),
  no: document.querySelector("#no-page"),
};

function showPage(name) {
  for (const [key, el] of Object.entries(pages)) {
    el.hidden = key !== name;
  }
}

async function answer(choice) {
  const res = await fetch(`${BACKEND_URL}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choice }),
  });
  const data = await res.json();
  return data.text;
}

async function go(choice, textEl, pageName) {
  textEl.textContent = "...";
  showPage(pageName);
  textEl.textContent = await answer(choice);
}

document.querySelector("#yes-btn").addEventListener("click", () =>
  go("yes", document.querySelector("#yes-text"), "yes"),
);
document.querySelector("#no-btn").addEventListener("click", () =>
  go("no", document.querySelector("#no-text"), "no"),
);

for (const btn of document.querySelectorAll(".back-btn")) {
  btn.addEventListener("click", () => showPage("question"));
}
