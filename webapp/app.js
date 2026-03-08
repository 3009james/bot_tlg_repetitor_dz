(function () {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor("#07204f");
    tg.setBackgroundColor("#03112d");
  }

  const state = {
    me: null,
    lessonTypes: [],
    students: [],
    selectedLessonTypeId: null,
    studentDashboard: [],
    studentActionMode: "start",
    student: { lessonTypeId: null, difficulty: null, quizId: null, questions: [], currentIndex: 0, answerMeta: {} },
  };

  const title = document.getElementById("title");
  const subtitle = document.getElementById("subtitle");
  const errorText = document.getElementById("errorText");
  const pendingView = document.getElementById("pendingView");
  const pendingSubject = document.getElementById("pendingSubject");
  const pendingMessage = document.getElementById("pendingMessage");
  const pendingSendBtn = document.getElementById("pendingSendBtn");
  const pendingStatus = document.getElementById("pendingStatus");
  const studentView = document.getElementById("studentView");
  const studentUpdateInfo = document.getElementById("studentUpdateInfo");
  const studentGenerateInfo = document.getElementById("studentGenerateInfo");
  const studentLessonTypeSelect = document.getElementById("studentLessonTypeSelect");
  const studentBeginBtn = document.getElementById("studentBeginBtn");
  const studentGenerateBtn = document.getElementById("studentGenerateBtn");
  const studentStartStage = document.getElementById("studentStartStage");
  const studentDifficultyStage = document.getElementById("studentDifficultyStage");
  const studentDifficultyTitle = document.getElementById("studentDifficultyTitle");
  const studentGeneratingStage = document.getElementById("studentGeneratingStage");
  const studentQuizStage = document.getElementById("studentQuizStage");
  const studentQuizProgress = document.getElementById("studentQuizProgress");
  const studentQuizQuestion = document.getElementById("studentQuizQuestion");
  const studentMcqWrap = document.getElementById("studentMcqWrap");
  const studentQuizOptions = document.getElementById("studentQuizOptions");
  const studentCodeWrap = document.getElementById("studentCodeWrap");
  const studentCodeInput = document.getElementById("studentCodeInput");
  const studentCodeCheckBtn = document.getElementById("studentCodeCheckBtn");
  const studentSuggestedCodeWrap = document.getElementById("studentSuggestedCodeWrap");
  const studentSuggestedCode = document.getElementById("studentSuggestedCode");
  const studentQuizFeedback = document.getElementById("studentQuizFeedback");
  const studentShowSolutionBtn = document.getElementById("studentShowSolutionBtn");
  const studentPrevQuestionBtn = document.getElementById("studentPrevQuestionBtn");
  const studentNextQuestionBtn = document.getElementById("studentNextQuestionBtn");
  const studentRestartBtn = document.getElementById("studentRestartBtn");
  const studentResultInfo = document.getElementById("studentResultInfo");
  const adminView = document.getElementById("adminView");
  const adminLessonTypesBtn = document.getElementById("adminLessonTypesBtn");
  const adminRequestsWrap = document.getElementById("adminRequestsWrap");
  const adminLessonTypesList = document.getElementById("adminLessonTypesList");
  const adminLessonTypesWrap = document.getElementById("adminLessonTypesWrap");
  const adminLessonTypePanel = document.getElementById("adminLessonTypePanel");
  const adminLessonTypeTitle = document.getElementById("adminLessonTypeTitle");
  const adminBackToLessonTypesBtn = document.getElementById("adminBackToLessonTypesBtn");
  const adminLessonTypeFileInput = document.getElementById("adminLessonTypeFileInput");
  const adminLessonTypeUploadBtn = document.getElementById("adminLessonTypeUploadBtn");
  const adminLessonTypeUploadStatus = document.getElementById("adminLessonTypeUploadStatus");
  const adminMaterialsWrap = document.getElementById("adminMaterialsWrap");
  const adminAvailableTopics = document.getElementById("adminAvailableTopics");
  const adminTopicsChecklist = document.getElementById("adminTopicsChecklist");
  const adminSelectAllTopicsBtn = document.getElementById("adminSelectAllTopicsBtn");
  const adminClearTopicsBtn = document.getElementById("adminClearTopicsBtn");
  const adminStudentsAssignWrap = document.getElementById("adminStudentsAssignWrap");
  const adminSaveStudentsAssignBtn = document.getElementById("adminSaveStudentsAssignBtn");
  const adminSaveTopicsBtn = document.getElementById("adminSaveTopicsBtn");
  const adminGenerateDayStatus = document.getElementById("adminGenerateDayStatus");
  const adminPackViewWrap = document.getElementById("adminPackViewWrap");

  const setHidden = (el, hidden) => (hidden ? el.classList.add("hidden") : el.classList.remove("hidden"));
  const showError = (msg) => {
    if (!msg) {
      errorText.classList.add("hidden");
      errorText.textContent = "";
      return;
    }
    errorText.classList.remove("hidden");
    errorText.textContent = String(msg);
  };
  const notify = (msg) => {
    if (!msg) return;
    if (tg && tg.showAlert) return tg.showAlert(String(msg));
    window.alert(String(msg));
  };

  async function api(path, options = {}) {
    if (!tg || !tg.initData) throw new Error("Откройте приложение через Telegram.");
    const headers = { "X-Telegram-Init-Data": tg.initData, ...(options.headers || {}) };
    const body = options.body;
    if (!(body instanceof FormData)) headers["Content-Type"] = headers["Content-Type"] || "application/json";
    const response = await fetch(path, { method: options.method || "GET", headers, body });
    let data = {};
    let raw = "";
    try {
      data = await response.json();
    } catch (_e) {
      try {
        raw = await response.text();
      } catch (_e2) {}
    }
    if (!response.ok) throw new Error(data.detail || "HTTP " + response.status + ": " + (raw ? raw.slice(0, 180) : "Ошибка API"));
    return data;
  }

  function showRoleView(role) {
    [pendingView, studentView, adminView].forEach((el) => setHidden(el, true));
    if (role === "admin") return setHidden(adminView, false);
    if (role === "student") return setHidden(studentView, false);
    setHidden(pendingView, false);
  }
  function setStudentStage(stage) {
    setHidden(studentStartStage, stage !== "start");
    setHidden(studentDifficultyStage, stage !== "difficulty");
    setHidden(studentGeneratingStage, stage !== "generating");
    setHidden(studentQuizStage, stage !== "quiz");
  }
  function currentStudentLesson() {
    const id = Number(studentLessonTypeSelect.value || 0);
    return state.studentDashboard.find((x) => x.id === id) || null;
  }

  function renderStudentLessonInfo() {
    const lesson = currentStudentLesson();
    if (!lesson) {
      studentUpdateInfo.textContent = "Вы еще не закреплены ни за одним видом занятия.";
      studentGenerateInfo.textContent = "";
      return;
    }
    const updated = lesson.updated_at ? new Date(lesson.updated_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) : null;
    studentUpdateInfo.textContent = updated ? "Последние задания обновлены: " + updated + " (МСК)" : "Заданий пока нет. Можно создать новые.";
    if (lesson.can_generate_now) studentGenerateInfo.textContent = "Новые задачи доступны.";
    else {
      const nextAt = lesson.next_generation_at
        ? new Date(lesson.next_generation_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })
        : "";
      studentGenerateInfo.textContent = "Новые задачи будут доступны после: " + nextAt + " (МСК)";
    }
  }

  async function loadStudentDashboard() {
    const dashboard = await api("/api/student/dashboard");
    state.studentDashboard = dashboard.lesson_types || [];
    studentLessonTypeSelect.innerHTML = "";
    state.studentDashboard.forEach((x) => {
      const opt = document.createElement("option");
      opt.value = x.id;
      opt.textContent = x.name;
      studentLessonTypeSelect.appendChild(opt);
    });
    renderStudentLessonInfo();
  }

  async function loadPendingStatus() {
    const status = await api("/api/access/status");
    pendingStatus.textContent = status.has_pending_request ? "Заявка уже отправлена и ожидает подтверждения." : "Заявка пока не отправлена.";
  }

  function renderRequests(items) {
    adminRequestsWrap.innerHTML = "";
    if (!items.length) {
      adminRequestsWrap.innerHTML = '<div class="admin-item">Новых заявок нет.</div>';
      return;
    }
    items.forEach((req) => {
      const item = document.createElement("div");
      item.className = "admin-item";
      item.innerHTML =
        '<p class="admin-item-title">#' +
        req.id +
        " " +
        req.full_name +
        "</p><p>@" +
        (req.username || "-") +
        " | tg_id=" +
        req.telegram_id +
        "</p><p>Предмет: " +
        (req.subject || "-") +
        "</p><p>Комментарий: " +
        (req.message || "-") +
        "</p>";
      const row = document.createElement("div");
      row.className = "admin-row";
      [["Подтвердить", "approve"], ["Отклонить", "reject"]].forEach(([label, action]) => {
        const b = document.createElement("button");
        b.className = "mini-btn";
        b.textContent = label;
        b.addEventListener("click", async () => {
          await api("/api/admin/requests/" + req.id + "/" + action, { method: "POST" });
          await loadAdminRequests();
        });
        row.appendChild(b);
      });
      item.appendChild(row);
      adminRequestsWrap.appendChild(item);
    });
  }
  async function loadAdminRequests() {
    const data = await api("/api/admin/requests");
    renderRequests(data.items || []);
  }

  function renderLessonTypes(items) {
    adminLessonTypesWrap.innerHTML = "";
    items.forEach((row) => {
      const item = document.createElement("div");
      item.className = "admin-item";
      item.innerHTML =
        '<p class="admin-item-title">' +
        row.name +
        "</p><p>Материалы: " +
        row.materials_count +
        " | Темы: " +
        row.topics_count +
        " | Ученики: " +
        row.students_count +
        "</p>";
      const openBtn = document.createElement("button");
      openBtn.className = "mini-btn";
      openBtn.textContent = "Открыть";
      openBtn.addEventListener("click", async () => {
        state.selectedLessonTypeId = row.id;
        await loadLessonTypePanel(row.id);
      });
      item.appendChild(openBtn);
      adminLessonTypesWrap.appendChild(item);
    });
  }
  async function loadLessonTypes() {
    const data = await api("/api/admin/lesson-types");
    state.lessonTypes = data.items || [];
    renderLessonTypes(state.lessonTypes);
  }

  function renderStudentsAssign(assigned) {
    const assignedSet = new Set((assigned || []).map((x) => x.id));
    adminStudentsAssignWrap.innerHTML = "";
    state.students.forEach((s) => {
      const row = document.createElement("label");
      row.className = "admin-item";
      row.innerHTML =
        '<input type="checkbox" class="assign-student-checkbox" value="' +
        s.id +
        '"' +
        (assignedSet.has(s.id) ? " checked" : "") +
        "/>" +
        s.full_name +
        " (tg_id=" +
        s.telegram_id +
        ")";
      adminStudentsAssignWrap.appendChild(row);
    });
  }

  function renderMaterials(items) {
    adminMaterialsWrap.innerHTML = "";
    if (!items || !items.length) return (adminMaterialsWrap.innerHTML = '<div class="admin-item">Материалов пока нет.</div>');
    items.forEach((m) => {
      const item = document.createElement("div");
      item.className = "admin-item";
      const created = m.created_at ? new Date(m.created_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) : "-";
      const topics = Array.isArray(m.topics) && m.topics.length ? m.topics.join(", ") : "темы не выделены";
      item.innerHTML =
        '<p class="admin-item-title">' +
        (m.title || m.source_filename || "Материал #" + m.id) +
        "</p><p>Файл: " +
        (m.source_filename || "-") +
        "</p><p>Темы: " +
        topics +
        "</p><p>Добавлен: " +
        created +
        " | tokens~" +
        Number(m.tokens_estimate || 0) +
        "</p>";
      const del = document.createElement("button");
      del.className = "mini-btn";
      del.textContent = "Удалить";
      del.dataset.action = "delete-material";
      del.dataset.materialId = String(m.id);
      item.appendChild(del);
      adminMaterialsWrap.appendChild(item);
    });
  }

  function renderTopicChecklist(availableTopics, selectedTopics) {
    const selected = new Set(Array.isArray(selectedTopics) ? selectedTopics : []);
    const merged = [];
    const seen = new Set();
    (Array.isArray(availableTopics) ? availableTopics : []).forEach((t) => {
      const x = String(t || "").trim();
      if (!x || seen.has(x)) return;
      seen.add(x);
      merged.push(x);
    });
    selected.forEach((t) => {
      const x = String(t || "").trim();
      if (!x || seen.has(x)) return;
      seen.add(x);
      merged.push(x);
    });
    adminTopicsChecklist.innerHTML = "";
    if (!merged.length) return (adminTopicsChecklist.innerHTML = '<div class="admin-item">Темы пока не обнаружены, сначала загрузите материалы.</div>');
    merged.forEach((topic) => {
      const row = document.createElement("label");
      row.className = "admin-item";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "topic-checkbox";
      cb.value = topic;
      cb.checked = selected.has(topic);
      row.appendChild(cb);
      row.appendChild(document.createTextNode(" " + topic));
      adminTopicsChecklist.appendChild(row);
    });
  }

  async function loadLessonTypePanel(id) {
    const details = await api("/api/admin/lesson-types/" + id);
    const students = await api("/api/admin/students");
    state.students = students.items || [];
    adminLessonTypeTitle.textContent = "Вид занятия: " + details.name;
    adminAvailableTopics.textContent = details.available_topics.length
      ? "Найдено тем: " + details.available_topics.length
      : "Темы пока не обнаружены, сначала загрузите материалы.";
    renderTopicChecklist(details.available_topics || [], details.selected_topics || []);
    renderStudentsAssign(details.students || []);
    renderMaterials(details.materials || []);
    adminPackViewWrap.innerHTML = "";
    adminGenerateDayStatus.textContent = "";
    setHidden(adminLessonTypesList, true);
    setHidden(adminLessonTypePanel, false);
  }

  async function saveLessonTypeTopics() {
    const topics = Array.from(document.querySelectorAll(".topic-checkbox:checked")).map((x) => String(x.value || "").trim()).filter(Boolean);
    await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/topics", { method: "POST", body: JSON.stringify({ topics }) });
  }
  async function saveLessonTypeStudents() {
    const ids = Array.from(document.querySelectorAll(".assign-student-checkbox:checked")).map((x) => Number(x.value));
    await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/students", { method: "POST", body: JSON.stringify({ student_ids: ids }) });
  }

  async function uploadLessonTypeMaterial() {
    const file = adminLessonTypeFileInput.files && adminLessonTypeFileInput.files[0];
    if (!file) throw new Error("Выберите файл .txt, .docx или .pdf");
    const lower = String(file.name || "").toLowerCase();
    if (!(lower.endsWith(".txt") || lower.endsWith(".docx") || lower.endsWith(".pdf"))) throw new Error("Поддерживаются только .txt, .docx, .pdf");
    const form = new FormData();
    form.append("file", file);
    adminLessonTypeUploadBtn.disabled = true;
    adminLessonTypeUploadBtn.textContent = "Загрузка...";
    const res = await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/materials/upload", { method: "POST", body: form });
    await loadLessonTypePanel(state.selectedLessonTypeId);
    const topics = Array.isArray(res.topics) ? res.topics : [];
    const created = res.status !== "duplicate";
    adminLessonTypeUploadStatus.textContent = (created ? "Материал загружен." : "Дубликат файла, повторная загрузка не нужна.") + (topics.length ? " Темы: " + topics.join(", ") : "");
    adminLessonTypeFileInput.value = "";
    adminLessonTypeUploadBtn.disabled = false;
    adminLessonTypeUploadBtn.textContent = "Загрузить материал";
    notify(created ? "Материал загружен" : "Этот материал уже был загружен");
  }

  async function generateLessonTypeByDifficulty(difficulty, btn) {
    const all = Array.from(document.querySelectorAll(".admin-generate-diff"));
    all.forEach((b) => (b.disabled = true));
    const old = btn.textContent;
    btn.textContent = "Генерация...";
    adminGenerateDayStatus.textContent = "Генерация заданий запущена...";
    try {
      const res = await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/generate", {
        method: "POST",
        body: JSON.stringify({ difficulty }),
      });
      adminGenerateDayStatus.textContent = "Генерация завершена. Сложность: " + res.difficulty + ". Учеников: " + res.students_count + ".";
    } finally {
      all.forEach((b) => (b.disabled = false));
      btn.textContent = old;
    }
  }

  function renderPack(questions) {
    adminPackViewWrap.innerHTML = "";
    (questions || []).forEach((q, i) => {
      const item = document.createElement("div");
      item.className = "admin-item";
      if (q.type === "code") {
        item.innerHTML = "<p class='admin-item-title'>#" + (i + 1) + " [Практика] " + q.question + "</p><p><b>Решение:</b> " + (q.explanation || "-") + "</p>";
      } else {
        const opts = (q.options || []).map((o, j) => j + 1 + ". " + o).join("<br/>");
        item.innerHTML =
          "<p class='admin-item-title'>#" +
          (i + 1) +
          " " +
          q.question +
          "</p><p>" +
          opts +
          "</p><p><b>Правильный ответ:</b> " +
          (Number(q.correct_index || 0) + 1) +
          "</p><p><b>Решение:</b> " +
          (q.explanation || "-") +
          "</p>";
      }
      adminPackViewWrap.appendChild(item);
    });
  }
  async function openPackByDifficulty(d) {
    const res = await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/daily-pack?difficulty=" + encodeURIComponent(d));
    renderPack(res.questions || []);
  }

  async function refreshStudentQuizData() {
    if (!state.student.quizId) return;
    const quiz = await api("/api/student/tests/" + state.student.quizId);
    state.student.questions = quiz.questions || [];
    state.student.answerMeta = {};
    Object.keys(quiz.answers_by_position || {}).forEach((k) => (state.student.answerMeta[Number(k)] = quiz.answers_by_position[k]));
    const result = await api("/api/student/tests/" + state.student.quizId + "/result");
    studentResultInfo.textContent = "Прогресс: " + result.answered + "/" + result.total + ". Верно: " + result.correct + ".";
  }
  function showFeedback(text, ok) {
    studentQuizFeedback.classList.remove("hidden");
    studentQuizFeedback.className = ok ? "feedback feedback-ok" : "feedback feedback-bad";
    studentQuizFeedback.textContent = text;
  }

  function renderStudentQuestion() {
    if (!state.student.questions.length) return;
    const q = state.student.questions[state.student.currentIndex];
    studentQuizProgress.textContent = "Вопрос " + (state.student.currentIndex + 1) + "/" + state.student.questions.length;
    studentQuizQuestion.textContent = q.question;
    studentQuizOptions.innerHTML = "";
    studentSuggestedCode.textContent = "";
    setHidden(studentSuggestedCodeWrap, true);
    studentQuizFeedback.classList.add("hidden");
    studentShowSolutionBtn.classList.add("hidden");
    const meta = state.student.answerMeta[q.position];
    if (q.type === "code") {
      setHidden(studentCodeWrap, false);
      setHidden(studentMcqWrap, true);
      studentCodeInput.value = meta && meta.code_text ? String(meta.code_text) : "";
      if (meta && meta.feedback_text) showFeedback(String(meta.feedback_text), !!meta.is_correct);
      if (meta && meta.suggested_code) {
        studentSuggestedCode.textContent = String(meta.suggested_code);
        setHidden(studentSuggestedCodeWrap, false);
      }
      studentShowSolutionBtn.classList.remove("hidden");
      return;
    }
    setHidden(studentCodeWrap, true);
    setHidden(studentMcqWrap, false);
    if (meta) {
      showFeedback((meta.is_correct ? "Верно." : "Неверно.") + " Ответ: " + (Number(meta.selected_index) + 1) + ".", !!meta.is_correct);
      studentShowSolutionBtn.classList.remove("hidden");
    }
    (q.options || []).forEach((opt, idx) => {
      const b = document.createElement("button");
      b.className = "option-btn";
      b.textContent = opt;
      b.addEventListener("click", async () => {
        try {
          showError("");
          const res = await api("/api/student/tests/answer", {
            method: "POST",
            body: JSON.stringify({ quiz_id: state.student.quizId, position: q.position, selected_index: idx }),
          });
          state.student.answerMeta[q.position] = {
            selected_index: idx,
            is_correct: res.is_correct,
            feedback_text: (res.is_correct ? "Верно." : "Неверно.") + " Правильный ответ: " + (Number(res.correct_option_index) + 1) + ".",
          };
          showFeedback(state.student.answerMeta[q.position].feedback_text, !!res.is_correct);
          studentShowSolutionBtn.classList.remove("hidden");
          await refreshStudentQuizData();
        } catch (err) {
          showError(err.message || err);
        }
      });
      studentQuizOptions.appendChild(b);
    });
  }

  async function startStudentTest(difficulty) {
    state.student.lessonTypeId = Number(studentLessonTypeSelect.value);
    state.student.difficulty = difficulty;
    const res = await api("/api/student/tests/start", {
      method: "POST",
      body: JSON.stringify({ lesson_type_id: state.student.lessonTypeId, difficulty, restart: true }),
    });
    state.student.quizId = res.quiz_id;
    state.student.questions = res.questions || [];
    state.student.currentIndex = 0;
    state.student.answerMeta = {};
    setStudentStage("quiz");
    await refreshStudentQuizData();
    renderStudentQuestion();
  }
  async function generateStudentTasks(difficulty) {
    state.student.lessonTypeId = Number(studentLessonTypeSelect.value);
    state.student.difficulty = difficulty;
    setStudentStage("generating");
    const res = await api("/api/student/lesson-types/" + state.student.lessonTypeId + "/generate", {
      method: "POST",
      body: JSON.stringify({ difficulty }),
    });
    state.student.quizId = res.quiz_id;
    state.student.questions = res.questions || [];
    state.student.currentIndex = 0;
    state.student.answerMeta = {};
    await loadStudentDashboard();
    setStudentStage("quiz");
    await refreshStudentQuizData();
    renderStudentQuestion();
    notify("Новые задачи сгенерированы");
  }

  pendingSendBtn.addEventListener("click", async () => {
    try {
      showError("");
      await api("/api/access/request", { method: "POST", body: JSON.stringify({ subject: pendingSubject.value || "", message: pendingMessage.value || "" }) });
      await loadPendingStatus();
    } catch (err) {
      showError(err.message || err);
    }
  });
  studentLessonTypeSelect.addEventListener("change", renderStudentLessonInfo);
  studentBeginBtn.addEventListener("click", () => {
    state.studentActionMode = "start";
    studentDifficultyTitle.textContent = "Выберите сложность для прохождения";
    setStudentStage("difficulty");
  });
  studentGenerateBtn.addEventListener("click", () => {
    const lesson = currentStudentLesson();
    if (!lesson) return;
    if (!lesson.can_generate_now) {
      const nextAt = lesson.next_generation_at ? new Date(lesson.next_generation_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) : "";
      return showError("Новые задачи будут доступны после " + nextAt + " (МСК)");
    }
    state.studentActionMode = "generate";
    studentDifficultyTitle.textContent = "Выберите сложность для генерации";
    setStudentStage("difficulty");
  });
  document.querySelectorAll(".student-difficulty").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        showError("");
        if (state.studentActionMode === "generate") await generateStudentTasks(btn.dataset.difficulty);
        else await startStudentTest(btn.dataset.difficulty);
      } catch (err) {
        const msg = String((err && err.message) || err || "");
        if (msg.includes("No tasks yet")) showError("Заданий пока нет. Нажмите «Новые задачи» и выберите сложность.");
        else showError(msg);
        setStudentStage("start");
      }
    });
  });
  studentCodeCheckBtn.addEventListener("click", async () => {
    try {
      showError("");
      const q = state.student.questions[state.student.currentIndex];
      if (!q || q.type !== "code") return;
      const code = String(studentCodeInput.value || "").trim();
      const res = await api("/api/student/tests/code-check", {
        method: "POST",
        body: JSON.stringify({ quiz_id: state.student.quizId, position: q.position, code }),
      });
      state.student.answerMeta[q.position] = {
        is_correct: !!res.is_correct,
        code_text: code,
        feedback_text: String(res.feedback || ""),
        suggested_code: String(res.suggested_code || ""),
      };
      showFeedback(String(res.feedback || ""), !!res.is_correct);
      if (res.suggested_code) {
        studentSuggestedCode.textContent = String(res.suggested_code);
        setHidden(studentSuggestedCodeWrap, false);
      }
      studentShowSolutionBtn.classList.remove("hidden");
      await refreshStudentQuizData();
    } catch (err) {
      showError(err.message || err);
    }
  });
  studentPrevQuestionBtn.addEventListener("click", () => {
    if (state.student.currentIndex <= 0) return;
    state.student.currentIndex -= 1;
    renderStudentQuestion();
  });
  studentNextQuestionBtn.addEventListener("click", () => {
    if (state.student.currentIndex >= state.student.questions.length - 1) return;
    state.student.currentIndex += 1;
    renderStudentQuestion();
  });
  studentShowSolutionBtn.addEventListener("click", () => {
    const q = state.student.questions[state.student.currentIndex];
    if (!q) return;
    showFeedback("Решение: " + (q.solution || "Решение не указано."), true);
  });
  studentRestartBtn.addEventListener("click", async () => {
    try {
      showError("");
      if (!state.student.difficulty) return setStudentStage("difficulty");
      await startStudentTest(state.student.difficulty);
    } catch (err) {
      showError(err.message || err);
    }
  });

  adminLessonTypesBtn.addEventListener("click", async () => {
    try {
      showError("");
      setHidden(adminLessonTypesList, false);
      setHidden(adminLessonTypePanel, true);
      await loadLessonTypes();
    } catch (err) {
      showError(err.message || err);
    }
  });
  adminBackToLessonTypesBtn.addEventListener("click", async () => {
    setHidden(adminLessonTypePanel, true);
    setHidden(adminLessonTypesList, false);
    await loadLessonTypes();
  });
  adminLessonTypeUploadBtn.addEventListener("click", async () => {
    try {
      showError("");
      await uploadLessonTypeMaterial();
    } catch (err) {
      adminLessonTypeUploadBtn.disabled = false;
      adminLessonTypeUploadBtn.textContent = "Загрузить материал";
      showError(err.message || err);
    }
  });
  adminMaterialsWrap.addEventListener("click", async (e) => {
    const t = e.target;
    if (!t || t.dataset.action !== "delete-material") return;
    try {
      showError("");
      await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/materials/" + Number(t.dataset.materialId), { method: "DELETE" });
      await loadLessonTypePanel(state.selectedLessonTypeId);
      adminLessonTypeUploadStatus.textContent = "Материал удален.";
      notify("Материал удален");
    } catch (err) {
      showError(err.message || err);
    }
  });
  adminSaveTopicsBtn.addEventListener("click", async () => {
    try {
      showError("");
      await saveLessonTypeTopics();
      await loadLessonTypePanel(state.selectedLessonTypeId);
      notify("Темы сохранены");
    } catch (err) {
      showError(err.message || err);
    }
  });
  adminSaveStudentsAssignBtn.addEventListener("click", async () => {
    try {
      showError("");
      await saveLessonTypeStudents();
      await loadLessonTypePanel(state.selectedLessonTypeId);
      notify("Закрепление сохранено");
    } catch (err) {
      showError(err.message || err);
    }
  });
  document.querySelectorAll(".admin-generate-diff").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        showError("");
        await generateLessonTypeByDifficulty(btn.dataset.difficulty, btn);
      } catch (err) {
        showError(err.message || err);
      }
    })
  );
  document.querySelectorAll(".admin-pack-diff").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        showError("");
        await openPackByDifficulty(btn.dataset.difficulty);
      } catch (err) {
        showError(err.message || err);
      }
    })
  );
  adminSelectAllTopicsBtn && adminSelectAllTopicsBtn.addEventListener("click", () => document.querySelectorAll(".topic-checkbox").forEach((x) => (x.checked = true)));
  adminClearTopicsBtn && adminClearTopicsBtn.addEventListener("click", () => document.querySelectorAll(".topic-checkbox").forEach((x) => (x.checked = false)));

  async function bootstrap() {
    try {
      showError("");
      const me = await api("/api/me");
      state.me = me;
      title.textContent = "Здравствуйте, " + me.full_name;
      if (me.role === "admin") {
        subtitle.textContent = "Панель администратора в приложении.";
        showRoleView("admin");
        return await loadAdminRequests();
      }
      if (me.role === "student") {
        subtitle.textContent = "Тестирование в приложении.";
        showRoleView("student");
        setStudentStage("start");
        return await loadStudentDashboard();
      }
      subtitle.textContent = "Доступ не выдан.";
      showRoleView("pending");
      await loadPendingStatus();
    } catch (err) {
      showError(err.message || err);
      subtitle.textContent = "Ошибка инициализации.";
    }
  }
  bootstrap();
})();
