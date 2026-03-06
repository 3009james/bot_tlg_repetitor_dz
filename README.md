# Telegram Tutor Bot (MVP)

MVP-бот для ваших учеников:
- роли `admin / student / pending` внутри Telegram Mini App
- в чате бота только кнопка `Открыть приложение`
- виды занятий: `C++ / Python / Математика`
- загрузка `ipynb` по виду занятия, выбор тем, закрепление учеников
- генерация пакета заданий на сутки по виду занятия (10 на каждую сложность)
- просмотр сгенерированных заданий в админ-панели
- тестирование ученика полностью в приложении с навигацией по вопросам
- ручной/автоматический режим генерации по времени
- экономия токенов: один пакет задач генерируется на вид занятия и переиспользуется для закрепленных учеников

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
   - `WEBAPP_URL` (публичный `https://` URL mini app)
4. Запуск:
   ```bash
   python -m src.main
   ```

## Логика прав
- Если `telegram_id` есть в `ADMIN_TELEGRAM_IDS`, пользователь автоматически админ.
- В чате бота остается только кнопка `Открыть приложение`.
- Новый пользователь отправляет заявку из Mini App.
- Админ одобряет/отклоняет заявки в Mini App.

## Загрузка материалов
1. Откройте Mini App под админом.
2. В блоке `Загрузка блокнота` выберите ученика.
3. Загрузите `.ipynb` файлом.
4. Материал сжимается и сохраняется в БД.

## Ежедневные задания
- Планировщик каждый день в `00:00` по `TIMEZONE` генерирует тесты на три сложности для всех учеников.
- Админ может вручную запускать генерацию (всем или конкретному ученику) в Mini App.

## Деплой на VPS через Docker
1. Установите Docker + Compose plugin:
   ```bash
   apt update && apt upgrade -y
   apt install -y ca-certificates curl gnupg
   install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   chmod a+r /etc/apt/keyrings/docker.asc
   echo \
     "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
     $(. /etc/os-release && echo $VERSION_CODENAME) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
   apt update
   apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   ```
2. Клонируйте проект:
   ```bash
   mkdir -p /opt/projects
   cd /opt/projects
   git clone <your_repo_url> bot_tlg_repetitor_dz
   cd bot_tlg_repetitor_dz
   ```
3. Подготовьте `.env`:
   ```bash
   cp .env.example .env
   nano .env
   ```
4. Первый запуск в фоне:
   ```bash
   docker compose up -d --build
   ```
5. Проверка:
   ```bash
   docker compose ps
   docker compose logs -f bot
   ```
6. Обновление версии:
   ```bash
   git pull
   docker compose up -d --build
   ```

## Mini App (темно-синий интерфейс)
- Фронтенд лежит в папке `webapp/` и поднимается контейнером `webapp` (nginx).
- Backend API для Mini App поднимается контейнером `api` и проксируется через nginx как `/api/*`.
- В `docker-compose.yml` Mini App доступен на порту `8080` VPS.
- Для Telegram Mini App нужен публичный `https://` URL. На практике:
  1. домен -> VPS,
  2. reverse proxy с TLS (Nginx/Caddy/Traefik или Cloudflare Tunnel),
  3. в `.env` бота указать `WEBAPP_URL=https://your-domain.example`.
- После `/start` пользователь видит кнопку `Открыть приложение`.
- Весь flow ученика и админа работает в приложении.

## Что дальше
- добавить полноценный режим `Вручную`
- добавить web-admin (FastAPI) при необходимости
- перенести БД на PostgreSQL при росте нагрузки
- добавить pgvector/эмбеддинги для более умного поиска по материалам
