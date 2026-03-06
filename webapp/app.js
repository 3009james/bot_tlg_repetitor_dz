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
  let studentsCache = [];

  const title = document.getElementById("title");
  const subtitle = document.getElementById("subtitle");
  const errorText = document.getElementById("errorText");

  const studentView = document.getElementById("studentView");
  const pendingView = document.getElementById("pendingView");
  const adminView = document.getElementById("adminView");

  const modeGroup = document.getElementById("modeGroup");
  const difficultyGroup = document.getElementById("difficultyGroup");
  const setupSection = document.getElementById("setupSection");
  const quizSection = document.getElementById("quizSection");
  const startBtn = document.getElementById("startBtn");
  const progressText = document.getElementById("progressText");
  const questionText = document.getElementById("questionText");
  const optionsWrap = document.getElementById("optionsWrap");
  const feedbackBox = document.getElementById("feedbackBox");
  const nextBtn = document.getElementById("nextBtn");

  const pendingSubject = document.getElementById("pendingSubject");
  const pendingMessage = document.getElementById("pendingMessage");
  const pendingSendBtn = document.getElementById("pendingSendBtn");
  const pendingStatus = document.getElementById("pendingStatus");

  const refreshAdminBtn = document.getElementById("refreshAdminBtn");
  const generateAllBtn = document.getElementById("generateAllBtn");
  const requestsWrap = document.getElementById("requestsWrap");
  const studentsWrap = document.getElementById("studentsWrap");
  const uploadStudentSelect = document.getElementById("uploadStudentSelect");
  const uploadFileInput = document.getElementById("uploadFileInput");
  const uploadBtn = document.getElementById("uploadBtn");
  const uploadStatus = document.getElementById("uploadStatus");

  function showError(message) {
    if (!message) {
      errorText.classList.add("hidden");
      errorText.textContent = "";
      return;
    }
    errorText.classList.remove("hidden");
    errorText.textContent = String(message);
  }

  function activateByData(container, key, value) {
    const items = container.querySelectorAll("button");
    items.forEach((btn) => {
      btn.classList.toggle("chip-active", btn.dataset[key] === value);
    });
  }

  function showRoleView(role) {
    studentView.classList.add("hidden");
    pendingView.classList.add("hidden");
    adminView.classList.add("hidden");
    if (role === "admin") {
      adminView.classList.remove("hidden");
      return;
    }
    if (role === "student") {
      studentView.classList.remove("hidden");
      return;
    }
    pendingView.classList.remove("hidden");
  }

  async function api(path, options = {}) {
    if (!tg || !tg.initData) {
      throw new Error("Откройте приложение через Telegram.");
    }
    const headers = {
      "X-Telegram-Init-Data": tg.initData,
      ...(options.headers || {}),
    };
    const body = options.body;
    if (!(body instanceof FormData)) {
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
    }
    const response = await fetch(path, {
      method: options.method || "GET",
      headers,
      body,
    });
    let data = {};
    try {
      data = await response.json();
    } catch (_err) {
      data = {};
    }
    if (!response.ok) {
      throw new Error(data.detail || "Ошибка API");
    }
    return data;
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
        optionsWrap.querySelectorAll("button").forEach((x) => {
          x.disabled = true;
        });
        try {
          const ans = await api("/api/quiz/answer", {
            method: "POST",
            body: JSON.stringify({ quiz_id: currentQuizId, selected_index: idx }),
          });
          const prefix = ans.feedback.is_correct ? "Верно." : "Неверно.";
          feedbackBox.textContent =
            prefix +
            " Правильный ответ: " +
            (ans.feedback.correct_option_index + 1) +
            ". " +
            (ans.feedback.explanation || "");
          feedbackBox.className = ans.feedback.is_correct ? "feedback feedback-ok" : "feedback feedback-bad";

          if (ans.status === "completed") {
            nextBtn.classList.add("hidden");
            title.textContent = "Тест завершен";
            subtitle.textContent = "Результат: " + ans.result.correct_answers + "/" + ans.result.total_questions;
            return;
          }
          queuedNext = ans.next_question;
          nextBtn.classList.remove("hidden");
        } catch (err) {
          showError(err.message || err);
        }
      });
      optionsWrap.appendChild(btn);
    });
  }

  async function startStudentQuiz() {
    if (mode === "manual") {
      showError("Режим вручную добавим следующим этапом.");
      return;
    }
    const start = await api("/api/quiz/start", {
      method: "POST",
      body: JSON.stringify({ difficulty }),
    });
    if (start.status === "completed") {
      setupSection.classList.add("hidden");
      quizSection.classList.remove("hidden");
      title.textContent = "Тест уже завершен";
      subtitle.textContent = "Результат: " + start.result.correct_answers + "/" + start.result.total_questions;
      questionText.textContent = "";
      optionsWrap.innerHTML = "";
      return;
    }
    setupSection.classList.add("hidden");
    quizSection.classList.remove("hidden");
    renderQuestion(start);
  }

  function fillUploadStudents(items) {
    uploadStudentSelect.innerHTML = "";
    items.forEach((student) => {
      const opt = document.createElement("option");
      opt.value = student.id;
      opt.textContent = student.full_name + (student.subject ? " (" + student.subject + ")" : "");
      uploadStudentSelect.appendChild(opt);
    });
  }

  function renderRequests(items) {
    requestsWrap.innerHTML = "";
    if (!items.length) {
      requestsWrap.innerHTML = '<div class="admin-item">Новых заявок нет.</div>';
      return;
    }
    items.forEach((req) => {
      const card = document.createElement("div");
      card.className = "admin-item";
      card.innerHTML =
        '<p class="admin-item-title">#' +
        req.id +
        " " +
        req.full_name +
        "</p>" +
        "<p>@" +
        (req.username || "-") +
        " | tg_id=" +
        req.telegram_id +
        "</p>" +
        "<p>Предмет: " +
        (req.subject || "-") +
        "</p>" +
        "<p>Комментарий: " +
        (req.message || "-") +
        "</p>";
      const row = document.createElement("div");
      row.className = "admin-row";
      const approveBtn = document.createElement("button");
      approveBtn.className = "mini-btn";
      approveBtn.textContent = "Одобрить";
      approveBtn.addEventListener("click", async () => {
        await api("/api/admin/requests/" + req.id + "/approve", { method: "POST" });
        await loadAdminData();
      });
      const rejectBtn = document.createElement("button");
      rejectBtn.className = "mini-btn";
      rejectBtn.textContent = "Отклонить";
      rejectBtn.addEventListener("click", async () => {
        await api("/api/admin/requests/" + req.id + "/reject", { method: "POST" });
        await loadAdminData();
      });
      row.appendChild(approveBtn);
      row.appendChild(rejectBtn);
      card.appendChild(row);
      requestsWrap.appendChild(card);
    });
  }

  function renderStudents(items) {
    studentsWrap.innerHTML = "";
    if (!items.length) {
      studentsWrap.innerHTML = '<div class="admin-item">Учеников пока нет.</div>';
      return;
    }

    items.forEach((student) => {
      const card = document.createElement("div");
      card.className = "admin-item";
      const topicsRaw = (student.selected_topics || []).join(", ");
      card.innerHTML =
        '<p class="admin-item-title">' +
        student.full_name +
        "</p>" +
        "<p>tg_id=" +
        student.telegram_id +
        " | предмет: " +
        (student.subject || "-") +
        "</p>" +
        '<input class="text-input topic-input" placeholder="Темы через запятую" value="' +
        topicsRaw.replace(/"/g, "&quot;") +
        '"/>';

      const row = document.createElement("div");
      row.className = "admin-row";

      const saveTopicsBtn = document.createElement("button");
      saveTopicsBtn.className = "mini-btn";
      saveTopicsBtn.textContent = "Сохранить темы";
      saveTopicsBtn.addEventListener("click", async () => {
        const input = card.querySelector(".topic-input");
        const topics = input.value
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
        await api("/api/admin/students/" + student.id + "/topics", {
          method: "POST",
          body: JSON.stringify({ topics }),
        });
        showError("");
      });

      const generateBtn = document.createElement("button");
      generateBtn.className = "mini-btn";
      generateBtn.textContent = "Сгенерировать";
      generateBtn.addEventListener("click", async () => {
        await api("/api/admin/students/" + student.id + "/generate", { method: "POST" });
        showError("");
      });

      row.appendChild(saveTopicsBtn);
      row.appendChild(generateBtn);
      card.appendChild(row);
      studentsWrap.appendChild(card);
    });
  }

  async function loadAdminData() {
    const [reqs, students] = await Promise.all([api("/api/admin/requests"), api("/api/admin/students")]);
    studentsCache = students.items || [];
    renderRequests(reqs.items || []);
    renderStudents(studentsCache);
    fillUploadStudents(studentsCache);
  }

  async function loadPendingState() {
    const status = await api("/api/access/status");
    if (status.has_pending_request) {
      pendingStatus.textContent = "Заявка уже отправлена и ожидает решения.";
    } else {
      pendingStatus.textContent = "Заявка пока не отправлена.";
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

  startBtn.addEventListener("click", async () => {
    try {
      showError("");
      await startStudentQuiz();
    } catch (err) {
      showError(err.message || err);
    }
  });

  nextBtn.addEventListener("click", () => {
    if (!queuedNext) return;
    renderQuestion(queuedNext);
  });

  pendingSendBtn.addEventListener("click", async () => {
    try {
      showError("");
      await api("/api/access/request", {
        method: "POST",
        body: JSON.stringify({
          subject: pendingSubject.value || "",
          message: pendingMessage.value || "",
        }),
      });
      await loadPendingState();
    } catch (err) {
      showError(err.message || err);
    }
  });

  refreshAdminBtn.addEventListener("click", async () => {
    try {
      showError("");
      await loadAdminData();
    } catch (err) {
      showError(err.message || err);
    }
  });

  generateAllBtn.addEventListener("click", async () => {
    try {
      showError("");
      await api("/api/admin/generate-all", { method: "POST" });
    } catch (err) {
      showError(err.message || err);
    }
  });

  uploadBtn.addEventListener("click", async () => {
    try {
      showError("");
      uploadStatus.textContent = "";
      const studentId = uploadStudentSelect.value;
      const file = uploadFileInput.files && uploadFileInput.files[0];
      if (!studentId || !file) {
        throw new Error("Выберите ученика и .ipynb файл.");
      }
      const form = new FormData();
      form.append("student_id", studentId);
      form.append("file", file);
      const result = await api("/api/admin/material/upload", {
        method: "POST",
        body: form,
      });
      uploadStatus.textContent = result.status === "duplicate" ? "Дубликат блокнота." : "Блокнот сохранен.";
    } catch (err) {
      showError(err.message || err);
    }
  });

  async function bootstrap() {
    try {
      showError("");
      const me = await api("/api/me");
      title.textContent = "Здравствуйте, " + me.full_name;
      if (me.role === "admin") {
        subtitle.textContent = "Админ-панель в приложении.";
        showRoleView("admin");
        await loadAdminData();
        return;
      }
      if (me.role === "student") {
        subtitle.textContent = "Обучение полностью в приложении.";
        showRoleView("student");
        return;
      }
      subtitle.textContent = "Доступ еще не выдан.";
      showRoleView("pending");
      await loadPendingState();
    } catch (err) {
      showError(err.message || err);
      subtitle.textContent = "Ошибка инициализации.";
    }
  }

  bootstrap();
})();
