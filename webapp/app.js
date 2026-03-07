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
    student: {
      lessonTypeId: null,
      difficulty: null,
      quizId: null,
      questions: [],
      currentIndex: 0,
      answerMeta: {},
    },
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
  const studentLessonTypeSelect = document.getElementById("studentLessonTypeSelect");
  const studentBeginBtn = document.getElementById("studentBeginBtn");
  const studentStartStage = document.getElementById("studentStartStage");
  const studentModeStage = document.getElementById("studentModeStage");
  const studentModeTestBtn = document.getElementById("studentModeTestBtn");
  const studentModeManualBtn = document.getElementById("studentModeManualBtn");
  const studentDifficultyStage = document.getElementById("studentDifficultyStage");
  const studentQuizStage = document.getElementById("studentQuizStage");
  const studentQuizProgress = document.getElementById("studentQuizProgress");
  const studentQuizQuestion = document.getElementById("studentQuizQuestion");
  const studentQuizOptions = document.getElementById("studentQuizOptions");
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
  const adminSelectedTopicsInput = document.getElementById("adminSelectedTopicsInput");
  const adminStudentsAssignWrap = document.getElementById("adminStudentsAssignWrap");
  const adminSaveStudentsAssignBtn = document.getElementById("adminSaveStudentsAssignBtn");
  const adminSaveTopicsBtn = document.getElementById("adminSaveTopicsBtn");
  const adminGenerateDayBtn = document.getElementById("adminGenerateDayBtn");
  const adminGenerateDayStatus = document.getElementById("adminGenerateDayStatus");
  const adminPackViewWrap = document.getElementById("adminPackViewWrap");
  const adminGenerationMode = document.getElementById("adminGenerationMode");
  const adminGenerateHour = document.getElementById("adminGenerateHour");
  const adminGenerateMinute = document.getElementById("adminGenerateMinute");
  const adminSaveScheduleBtn = document.getElementById("adminSaveScheduleBtn");

  function setHidden(el, hidden) {
    if (!el) return;
    if (hidden) el.classList.add("hidden");
    else el.classList.remove("hidden");
  }

  function showError(message) {
    if (!errorText) return;
    if (!message) {
      errorText.classList.add("hidden");
      errorText.textContent = "";
      return;
    }
    errorText.classList.remove("hidden");
    errorText.textContent = String(message);
  }

  function notify(message) {
    const text = String(message || "");
    if (!text) return;
    if (tg && typeof tg.showAlert === "function") {
      tg.showAlert(text);
      return;
    }
    window.alert(text);
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
    let rawText = "";
    try {
      data = await response.json();
    } catch (_err) {
      try {
        rawText = await response.text();
      } catch (_err2) {
        rawText = "";
      }
    }
    if (!response.ok) {
      const fallback = rawText ? rawText.slice(0, 180) : "Ошибка API";
      throw new Error(data.detail || "HTTP " + response.status + ": " + fallback);
    }
    return data;
  }

  function showRoleView(role) {
    setHidden(pendingView, true);
    setHidden(studentView, true);
    setHidden(adminView, true);
    if (role === "admin") {
      setHidden(adminView, false);
      return;
    }
    if (role === "student") {
      setHidden(studentView, false);
      return;
    }
    setHidden(pendingView, false);
  }

  async function loadPendingStatus() {
    const status = await api("/api/access/status");
    pendingStatus.textContent = status.has_pending_request
      ? "Заявка уже отправлена и ожидает подтверждения."
      : "Заявка пока не отправлена.";
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
      const approve = document.createElement("button");
      approve.className = "mini-btn";
      approve.textContent = "Подтвердить";
      approve.addEventListener("click", async () => {
        await api("/api/admin/requests/" + req.id + "/approve", { method: "POST" });
        await loadAdminRequests();
      });
      const reject = document.createElement("button");
      reject.className = "mini-btn";
      reject.textContent = "Отклонить";
      reject.addEventListener("click", async () => {
        await api("/api/admin/requests/" + req.id + "/reject", { method: "POST" });
        await loadAdminRequests();
      });
      row.appendChild(approve);
      row.appendChild(reject);
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
        "</p>" +
        "<p>Материалы: " +
        row.materials_count +
        " | Темы: " +
        row.topics_count +
        " | Ученики: " +
        row.students_count +
        "</p>" +
        "<p>Режим: " +
        row.generation_mode +
        " (" +
        String(row.generate_hour).padStart(2, "0") +
        ":" +
        String(row.generate_minute).padStart(2, "0") +
        ")</p>";
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

  function renderStudentsAssign(assignedStudents) {
    const assignedSet = new Set((assignedStudents || []).map((x) => x.id));
    adminStudentsAssignWrap.innerHTML = "";
    state.students.forEach((student) => {
      const row = document.createElement("label");
      row.className = "admin-item";
      row.innerHTML =
        '<input type="checkbox" class="assign-student-checkbox" value="' +
        student.id +
        '"' +
        (assignedSet.has(student.id) ? " checked" : "") +
        "/>" +
        student.full_name +
        " (tg_id=" +
        student.telegram_id +
        ")";
      adminStudentsAssignWrap.appendChild(row);
    });
  }

  function renderMaterials(items) {
    adminMaterialsWrap.innerHTML = "";
    if (!items || !items.length) {
      adminMaterialsWrap.innerHTML = '<div class="admin-item">Материалов пока нет.</div>';
      return;
    }
    items.forEach((m) => {
      const item = document.createElement("div");
      item.className = "admin-item";
      const created = m.created_at ? new Date(m.created_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) : "-";
      const topics = Array.isArray(m.topics) && m.topics.length ? m.topics.join(", ") : "темы не выделены";
      item.innerHTML =
        '<p class="admin-item-title">' +
        (m.title || m.source_filename || ("Материал #" + m.id)) +
        "</p>" +
        "<p>Файл: " +
        (m.source_filename || "-") +
        "</p>" +
        "<p>Темы: " +
        topics +
        "</p>" +
        "<p>Добавлен: " +
        created +
        " | tokens~" +
        Number(m.tokens_estimate || 0) +
        "</p>";
      const delBtn = document.createElement("button");
      delBtn.className = "mini-btn";
      delBtn.textContent = "Удалить";
      delBtn.dataset.materialId = String(m.id);
      delBtn.dataset.action = "delete-material";
      item.appendChild(delBtn);
      adminMaterialsWrap.appendChild(item);
    });
  }

  async function loadLessonTypePanel(lessonTypeId) {
    const details = await api("/api/admin/lesson-types/" + lessonTypeId);
    const students = await api("/api/admin/students");
    state.students = students.items || [];

    adminLessonTypeTitle.textContent = "Вид занятия: " + details.name;
    adminAvailableTopics.textContent = details.available_topics.length
      ? details.available_topics.join(", ")
      : "Темы пока не обнаружены, сначала загрузите материалы.";
    adminSelectedTopicsInput.value = (details.selected_topics || []).join(", ");
    adminGenerationMode.value = details.generation_mode || "manual";
    adminGenerateHour.value = details.generate_hour;
    adminGenerateMinute.value = details.generate_minute;
    renderStudentsAssign(details.students || []);
    renderMaterials(details.materials || []);
    adminPackViewWrap.innerHTML = "";
    adminGenerateDayStatus.textContent = "";

    setHidden(adminLessonTypesList, true);
    setHidden(adminLessonTypePanel, false);
  }

  async function deleteLessonTypeMaterial(materialId) {
    if (!state.selectedLessonTypeId) return;
    await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/materials/" + materialId, {
      method: "DELETE",
    });
    await loadLessonTypePanel(state.selectedLessonTypeId);
    adminLessonTypeUploadStatus.textContent = "Материал удален.";
    notify("Материал удален");
  }

  async function saveLessonTypeTopics() {
    if (!state.selectedLessonTypeId) return;
    const topics = adminSelectedTopicsInput.value
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/topics", {
      method: "POST",
      body: JSON.stringify({ topics }),
    });
  }

  async function saveLessonTypeStudents() {
    if (!state.selectedLessonTypeId) return;
    const selected = Array.from(document.querySelectorAll(".assign-student-checkbox:checked")).map((el) =>
      Number(el.value)
    );
    await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/students", {
      method: "POST",
      body: JSON.stringify({ student_ids: selected }),
    });
  }

  async function saveLessonTypeSchedule() {
    if (!state.selectedLessonTypeId) return;
    await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/schedule", {
      method: "POST",
      body: JSON.stringify({
        mode: adminGenerationMode.value,
        hour: Number(adminGenerateHour.value || 0),
        minute: Number(adminGenerateMinute.value || 0),
      }),
    });
  }

  async function uploadLessonTypeMaterial() {
    if (!state.selectedLessonTypeId) return;
    const file = adminLessonTypeFileInput.files && adminLessonTypeFileInput.files[0];
    if (!file) throw new Error("Выберите файл .txt, .docx или .pdf");
    const lower = (file.name || "").toLowerCase();
    if (!(lower.endsWith(".txt") || lower.endsWith(".docx") || lower.endsWith(".pdf"))) {
      throw new Error("Поддерживаются только .txt, .docx, .pdf");
    }
    const form = new FormData();
    form.append("file", file);
    adminLessonTypeUploadBtn.disabled = true;
    adminLessonTypeUploadBtn.textContent = "Загрузка...";
    const res = await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/materials/upload", {
      method: "POST",
      body: form,
    });
    await loadLessonTypePanel(state.selectedLessonTypeId);
    const topics = Array.isArray(res.topics) ? res.topics : [];
    const topicsText = topics.length ? " Темы: " + topics.join(", ") : "";
    const created = res.status !== "duplicate";
    adminLessonTypeUploadStatus.textContent = (created ? "Материал загружен." : "Дубликат файла, повторная загрузка не нужна.") + topicsText;
    adminLessonTypeFileInput.value = "";
    notify(created ? "Материал загружен" : "Этот материал уже был загружен");
    adminLessonTypeUploadBtn.disabled = false;
    adminLessonTypeUploadBtn.textContent = "Загрузить материал";
  }

  async function generateLessonTypeDay() {
    if (!state.selectedLessonTypeId) return;
    const res = await api("/api/admin/lesson-types/" + state.selectedLessonTypeId + "/generate", { method: "POST" });
    adminGenerateDayStatus.textContent =
      "Сгенерировано на " + res.date + ". Учеников: " + res.students_count + ". По 10 задач на каждую сложность.";
  }

  function renderPack(questions) {
    adminPackViewWrap.innerHTML = "";
    questions.forEach((q, idx) => {
      const item = document.createElement("div");
      item.className = "admin-item";
      const options = (q.options || []).map((opt, i) => (i + 1) + ". " + opt).join("<br/>");
      item.innerHTML =
        "<p class='admin-item-title'>#" +
        (idx + 1) +
        " " +
        q.question +
        "</p>" +
        "<p>" +
        options +
        "</p>" +
        "<p><b>Правильный ответ:</b> " +
        (Number(q.correct_index || 0) + 1) +
        "</p>" +
        "<p><b>Решение:</b> " +
        (q.explanation || "-") +
        "</p>";
      adminPackViewWrap.appendChild(item);
    });
  }

  async function openPackByDifficulty(difficulty) {
    if (!state.selectedLessonTypeId) return;
    const res = await api(
      "/api/admin/lesson-types/" + state.selectedLessonTypeId + "/daily-pack?difficulty=" + encodeURIComponent(difficulty)
    );
    renderPack(res.questions || []);
  }

  function fillStudentLessonTypes(items) {
    studentLessonTypeSelect.innerHTML = "";
    items.forEach((x) => {
      const option = document.createElement("option");
      option.value = x.id;
      option.textContent = x.name;
      studentLessonTypeSelect.appendChild(option);
    });
  }

  async function loadStudentDashboard() {
    const dashboard = await api("/api/student/dashboard");
    const lessonTypes = dashboard.lesson_types || [];
    if (!lessonTypes.length) {
      studentUpdateInfo.textContent = "Вы еще не закреплены ни за одним видом занятия.";
      studentLessonTypeSelect.innerHTML = "";
      return;
    }
    fillStudentLessonTypes(lessonTypes);
    const first = lessonTypes[0];
    state.student.lessonTypeId = first.id;
    const updateRaw = first.updated_at ? new Date(first.updated_at) : null;
    studentUpdateInfo.textContent = updateRaw
      ? "Занятия обновлены: " + updateRaw.toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) + " (МСК)"
      : "Занятия пока не генерировались автоматически.";
  }

  function setStudentStage(stage) {
    setHidden(studentStartStage, stage !== "start");
    setHidden(studentModeStage, stage !== "mode");
    setHidden(studentDifficultyStage, stage !== "difficulty");
    setHidden(studentQuizStage, stage !== "quiz");
  }

  async function startStudentTest(difficulty) {
    state.student.lessonTypeId = Number(studentLessonTypeSelect.value);
    state.student.difficulty = difficulty;
    const res = await api("/api/student/tests/start", {
      method: "POST",
      body: JSON.stringify({
        lesson_type_id: state.student.lessonTypeId,
        difficulty: difficulty,
        restart: true,
      }),
    });
    state.student.quizId = res.quiz_id;
    state.student.questions = res.questions || [];
    state.student.currentIndex = 0;
    state.student.answerMeta = {};
    setStudentStage("quiz");
    await refreshStudentQuizData();
    renderStudentQuestion();
  }

  async function refreshStudentQuizData() {
    if (!state.student.quizId) return;
    const quiz = await api("/api/student/tests/" + state.student.quizId);
    const byPos = quiz.answers_by_position || {};
    state.student.answerMeta = {};
    Object.keys(byPos).forEach((pos) => {
      state.student.answerMeta[Number(pos)] = byPos[pos];
    });
    const result = await api("/api/student/tests/" + state.student.quizId + "/result");
    studentResultInfo.textContent =
      "Прогресс: " + result.answered + "/" + result.total + ". Верно: " + result.correct + ".";
  }

  function renderStudentQuestion() {
    const questions = state.student.questions;
    if (!questions.length) return;
    const q = questions[state.student.currentIndex];
    studentQuizProgress.textContent = "Вопрос " + (state.student.currentIndex + 1) + "/" + questions.length;
    studentQuizQuestion.textContent = q.question;
    studentQuizOptions.innerHTML = "";
    studentQuizFeedback.classList.add("hidden");
    studentShowSolutionBtn.classList.add("hidden");

    const meta = state.student.answerMeta[q.position];
    if (meta) {
      studentQuizFeedback.classList.remove("hidden");
      studentQuizFeedback.className = meta.is_correct ? "feedback feedback-ok" : "feedback feedback-bad";
      studentQuizFeedback.textContent =
        (meta.is_correct ? "Верно." : "Неверно.") +
        " Ответ: " +
        (Number(meta.selected_index) + 1) +
        ".";
    }

    q.options.forEach((option, idx) => {
      const btn = document.createElement("button");
      btn.className = "option-btn";
      btn.textContent = option;
      btn.addEventListener("click", async () => {
        const res = await api("/api/student/tests/answer", {
          method: "POST",
          body: JSON.stringify({
            quiz_id: state.student.quizId,
            position: q.position,
            selected_index: idx,
          }),
        });
        state.student.answerMeta[q.position] = {
          selected_index: idx,
          is_correct: res.is_correct,
          solution: res.solution || "",
          correct_option_index: res.correct_option_index,
        };
        studentQuizFeedback.classList.remove("hidden");
        studentQuizFeedback.className = res.is_correct ? "feedback feedback-ok" : "feedback feedback-bad";
        studentQuizFeedback.textContent =
          (res.is_correct ? "Верно." : "Неверно.") +
          " Правильный ответ: " +
          (Number(res.correct_option_index) + 1) +
          ".";
        studentShowSolutionBtn.classList.remove("hidden");
        await refreshStudentQuizData();
      });
      studentQuizOptions.appendChild(btn);
    });
  }

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
      await loadPendingStatus();
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

  adminMaterialsWrap.addEventListener("click", async (event) => {
    const target = event.target;
    if (!target || target.dataset.action !== "delete-material") return;
    const materialId = Number(target.dataset.materialId);
    if (!materialId) return;
    try {
      showError("");
      await deleteLessonTypeMaterial(materialId);
    } catch (err) {
      showError(err.message || err);
    }
  });

  adminSaveTopicsBtn.addEventListener("click", async () => {
    try {
      showError("");
      await saveLessonTypeTopics();
      await loadLessonTypePanel(state.selectedLessonTypeId);
    } catch (err) {
      showError(err.message || err);
    }
  });

  adminSaveStudentsAssignBtn.addEventListener("click", async () => {
    try {
      showError("");
      await saveLessonTypeStudents();
      await loadLessonTypePanel(state.selectedLessonTypeId);
    } catch (err) {
      showError(err.message || err);
    }
  });

  adminGenerateDayBtn.addEventListener("click", async () => {
    try {
      showError("");
      await generateLessonTypeDay();
    } catch (err) {
      showError(err.message || err);
    }
  });

  document.querySelectorAll(".admin-pack-diff").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        showError("");
        await openPackByDifficulty(btn.dataset.difficulty);
      } catch (err) {
        showError(err.message || err);
      }
    });
  });

  adminSaveScheduleBtn.addEventListener("click", async () => {
    try {
      showError("");
      await saveLessonTypeSchedule();
    } catch (err) {
      showError(err.message || err);
    }
  });

  studentBeginBtn.addEventListener("click", () => {
    setStudentStage("mode");
  });

  studentModeManualBtn.addEventListener("click", () => {
    showError("Режим вручную добавим следующим этапом.");
  });

  studentModeTestBtn.addEventListener("click", () => {
    setStudentStage("difficulty");
  });

  document.querySelectorAll(".student-difficulty").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        showError("");
        await startStudentTest(btn.dataset.difficulty);
      } catch (err) {
        showError(err.message || err);
      }
    });
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
    const meta = state.student.answerMeta[q.position];
    if (!meta || !meta.solution) {
      studentQuizFeedback.textContent = "Решение не указано.";
      return;
    }
    studentQuizFeedback.classList.remove("hidden");
    studentQuizFeedback.className = "feedback feedback-ok";
    studentQuizFeedback.textContent = "Решение: " + meta.solution;
  });

  studentRestartBtn.addEventListener("click", async () => {
    try {
      showError("");
      if (!state.student.difficulty) {
        setStudentStage("difficulty");
        return;
      }
      await startStudentTest(state.student.difficulty);
    } catch (err) {
      showError(err.message || err);
    }
  });

  async function bootstrap() {
    try {
      showError("");
      const me = await api("/api/me");
      state.me = me;
      title.textContent = "Здравствуйте, " + me.full_name;
      if (me.role === "admin") {
        subtitle.textContent = "Панель администратора в приложении.";
        showRoleView("admin");
        await loadAdminRequests();
        return;
      }
      if (me.role === "student") {
        subtitle.textContent = "Тестирование в приложении.";
        showRoleView("student");
        setStudentStage("start");
        await loadStudentDashboard();
        return;
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
