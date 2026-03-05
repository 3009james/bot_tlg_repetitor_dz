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
  let currentQuizId = null;
  let queuedNext = null;

  const title = document.getElementById("title");
  const subtitle = document.getElementById("subtitle");
  const setupSection = document.getElementById("setupSection");
  const quizSection = document.getElementById("quizSection");
  const modeGroup = document.getElementById("modeGroup");
  const difficultyGroup = document.getElementById("difficultyGroup");
  const startBtn = document.getElementById("startBtn");
  const hintText = document.getElementById("hintText");
  const progressText = document.getElementById("progressText");
  const questionText = document.getElementById("questionText");
  const optionsWrap = document.getElementById("optionsWrap");
  const feedbackBox = document.getElementById("feedbackBox");
  const nextBtn = document.getElementById("nextBtn");

  function activateByData(container, key, value) {
    const items = container.querySelectorAll("button");
    items.forEach((btn) => {
      const isActive = btn.dataset[key] === value;
      btn.classList.toggle("chip-active", isActive);
    });
  }

  async function api(path, options) {
    if (!tg || !tg.initData) {
      throw new Error("Откройте приложение из Telegram.");
    }
    const headers = {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": tg.initData,
    };
    const response = await fetch(path, {
      ...options,
      headers: {
        ...headers,
        ...(options && options.headers ? options.headers : {}),
      },
    });
    const data = await response.json();
    if (!response.ok) {
      const msg = data && data.detail ? String(data.detail) : "Ошибка API";
      throw new Error(msg);
    }
    return data;
  }

  function showMessage(text) {
    subtitle.textContent = text;
    hintText.textContent = "";
  }

  function renderQuestion(payload) {
    currentQuizId = payload.quiz_id;
    progressText.textContent = "Задание " + payload.position + "/" + payload.total;
    questionText.textContent = payload.question.text;
    optionsWrap.innerHTML = "";
    feedbackBox.className = "feedback hidden";
    nextBtn.classList.add("hidden");
    queuedNext = null;

    payload.question.options.forEach((opt, idx) => {
      const btn = document.createElement("button");
      btn.className = "option-btn";
      btn.textContent = opt;
      btn.addEventListener("click", async () => {
        const optionButtons = optionsWrap.querySelectorAll("button");
        optionButtons.forEach((x) => {
          x.disabled = true;
        });
        try {
          const ans = await api("/api/quiz/answer", {
            method: "POST",
            body: JSON.stringify({
              quiz_id: currentQuizId,
              selected_index: idx,
            }),
          });
          const prefix = ans.feedback.is_correct ? "Верно." : "Неверно.";
          const correctLabel = ans.feedback.correct_option_index + 1;
          feedbackBox.textContent =
            prefix +
            " Правильный ответ: " +
            correctLabel +
            ". " +
            (ans.feedback.explanation || "");
          feedbackBox.className = ans.feedback.is_correct ? "feedback feedback-ok" : "feedback feedback-bad";
          if (ans.status === "completed") {
            nextBtn.classList.add("hidden");
            title.textContent = "Тест завершен";
            subtitle.textContent =
              "Результат: " + ans.result.correct_answers + "/" + ans.result.total_questions;
            return;
          }
          queuedNext = ans.next_question;
          nextBtn.classList.remove("hidden");
        } catch (err) {
          feedbackBox.textContent = String(err.message || err);
          feedbackBox.className = "feedback feedback-bad";
        }
      });
      optionsWrap.appendChild(btn);
    });
  }

  async function loadProfile() {
    try {
      const me = await api("/api/me");
      if (me.role !== "student") {
        setupSection.classList.add("hidden");
        showMessage("Доступ к обучению пока не выдан. Подайте заявку через чат бота.");
        return;
      }
      title.textContent = "Здравствуйте, " + me.full_name;
      subtitle.textContent = "Выберите режим и сложность для тренировки.";
    } catch (err) {
      setupSection.classList.add("hidden");
      showMessage(String(err.message || err));
    }
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
    (async () => {
      if (mode === "manual") {
        showMessage("Режим вручную добавим следующим этапом.");
        return;
      }
      try {
        const start = await api("/api/quiz/start", {
          method: "POST",
          body: JSON.stringify({ difficulty: difficulty }),
        });
        if (start.status === "completed") {
          setupSection.classList.add("hidden");
          quizSection.classList.remove("hidden");
          title.textContent = "Тест уже завершен";
          subtitle.textContent =
            "Результат: " + start.result.correct_answers + "/" + start.result.total_questions;
          questionText.textContent = "";
          optionsWrap.innerHTML = "";
          return;
        }
        setupSection.classList.add("hidden");
        quizSection.classList.remove("hidden");
        renderQuestion(start);
      } catch (err) {
        showMessage(String(err.message || err));
      }
    })();
  });

  nextBtn.addEventListener("click", () => {
    if (!queuedNext) return;
    renderQuestion(queuedNext);
  });

  loadProfile();
})();
