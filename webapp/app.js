(function () {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor("#07204f");
    tg.setBackgroundColor("#03112d");
  }

  let mode = "test";
  let difficulty = "easy";

  const modeGroup = document.getElementById("modeGroup");
  const difficultyGroup = document.getElementById("difficultyGroup");
  const startBtn = document.getElementById("startBtn");

  function activateByData(container, key, value) {
    const items = container.querySelectorAll("button");
    items.forEach((btn) => {
      const isActive = btn.dataset[key] === value;
      btn.classList.toggle("chip-active", isActive);
    });
  }

  modeGroup.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-mode]");
    if (!btn) return;
    mode = btn.dataset.mode;
    activateByData(modeGroup, "mode", mode);
  });

  difficultyGroup.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-difficulty]");
    if (!btn) return;
    difficulty = btn.dataset.difficulty;
    activateByData(difficultyGroup, "difficulty", difficulty);
  });

  startBtn.addEventListener("click", () => {
    if (!tg) {
      alert("Откройте эту страницу через Telegram Mini App.");
      return;
    }
    const payload =
      mode === "manual"
        ? { action: "manual" }
        : { action: "start_quiz", difficulty: difficulty };
    tg.sendData(JSON.stringify(payload));
    tg.close();
  });
})();
