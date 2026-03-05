# Telegram Tutor Bot (MVP)

MVP-бот для ваших учеников:
- роли `admin / student / pending`
- заявки от новых пользователей
- загрузка `ipynb` через админку
- сжатие материала урока (через RouterAI API или fallback)
- генерация ежедневных тестов в `00:00` (easy/medium/hard)
- прохождение теста по одному вопросу с вариантами ответа

## Технологии
- Python 3.11+
- `aiogram 3`
- `SQLAlchemy + SQLite`
- `APScheduler`

## Быстрый старт (локально)
1. Создайте окружение и установите зависимости:
   ```bash
   python -m venv .venv
   .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```
2. Создайте `.env` на основе `.env.example`.
3. Укажите:
   - `BOT_TOKEN`
   - `ADMIN_TELEGRAM_IDS` (через запятую)
   - `ROUTERAI_API_KEY` (если пусто, будет fallback-генерация)
4. Запуск:
   ```bash
   python -m src.main
   ```

## Логика прав
- Если `telegram_id` есть в `ADMIN_TELEGRAM_IDS`, пользователь автоматически админ.
- Новый пользователь видит только кнопку отправки заявки.
- Админ одобряет заявку из раздела `Заявки`, после этого пользователь становится учеником.

## Загрузка материалов
1. В админке нажмите `Загрузить блокнот`.
2. Выберите ученика.
3. Отправьте `.ipynb` файлом.
4. Материал сжимается и сохраняется в БД.

## Ежедневные задания
- Планировщик каждый день в `00:00` по `TIMEZONE` генерирует тесты на три сложности для всех учеников.
- Админ может вручную нажать `Сгенерировать задания`.

## Деплой на VPS (базовый путь)
1. На локали:
   ```bash
   git init
   git add .
   git commit -m "init bot mvp"
   git remote add origin <your_repo_url>
   git push -u origin main
   ```
2. На VPS:
   ```bash
   git clone <your_repo_url>
   cd tlg_bot_dz
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   # заполнить .env
   python -m src.main
   ```
3. Обновление на VPS:
   ```bash
   git pull
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Что дальше
- добавить полноценный режим `Вручную`
- добавить web-admin (FastAPI) при необходимости
- перенести БД на PostgreSQL при росте нагрузки
- добавить pgvector/эмбеддинги для более умного поиска по материалам
