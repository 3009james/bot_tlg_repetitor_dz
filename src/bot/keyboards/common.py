from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo


def unknown_user_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить заявку")]],
        resize_keyboard=True,
    )


def student_home_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пройти обучение")]],
        resize_keyboard=True,
    )


def student_webapp_kb(webapp_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=webapp_url))],
            [KeyboardButton(text="Пройти обучение")],
        ],
        resize_keyboard=True,
    )


def admin_home_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Заявки"), KeyboardButton(text="Ученики")],
            [KeyboardButton(text="Загрузить блокнот"), KeyboardButton(text="Темы ученика")],
            [KeyboardButton(text="Сгенерировать задания")],
        ],
        resize_keyboard=True,
    )


def mode_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Тестирование"), KeyboardButton(text="Вручную (скоро)")]],
        resize_keyboard=True,
    )


def difficulty_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Легко"), KeyboardButton(text="Средне"), KeyboardButton(text="Сложно")]],
        resize_keyboard=True,
    )


def request_actions_kb(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Одобрить", callback_data=f"req:approve:{request_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"req:reject:{request_id}"),
            ]
        ]
    )


def student_select_kb(students: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"pick_student:{sid}")]
            for sid, name in students
        ]
    )


def topic_select_student_kb(students: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"topic_student:{sid}")]
            for sid, name in students
        ]
    )


def topic_manage_kb(student_id: int, topics: list[str], selected_topics: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, topic in enumerate(topics):
        prefix = "[x]" if topic in selected_topics else "[ ]"
        label = f"{prefix} {topic}"
        if len(label) > 64:
            label = label[:61] + "..."
        rows.append([InlineKeyboardButton(text=label, callback_data=f"topic_toggle:{student_id}:{idx}")])
    rows.append(
        [
            InlineKeyboardButton(text="Очистить", callback_data=f"topic_clear:{student_id}"),
            InlineKeyboardButton(text="Сгенерировать", callback_data=f"topic_generate:{student_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def question_options_kb(quiz_id: int, position: int, options: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i, option in enumerate(options):
        text = option if len(option) <= 48 else option[:45] + "..."
        rows.append([InlineKeyboardButton(text=text, callback_data=f"ans:{quiz_id}:{position}:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def next_question_kb(quiz_id: int, next_position: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Следующее задание", callback_data=f"next:{quiz_id}:{next_position}")]]
    )
