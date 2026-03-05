from __future__ import annotations

import json
import logging
import random

import httpx

log = logging.getLogger(__name__)


class RouterAIClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def summarize_lesson(self, raw_text: str) -> str:
        if not self.api_key:
            return self._cheap_summary(raw_text)
        prompt = (
            "Сожми материал занятия в компактный учебный конспект. "
            "Формат: ключевые темы, важные формулы/правила, типичные ошибки, 10-20 тезисов. "
            "Пиши по-русски, без воды."
        )
        content = await self._chat_json(prompt, raw_text, expect_json=False)
        return content.strip() or self._cheap_summary(raw_text)

    async def generate_questions(self, compact_context: str, difficulty: str, count: int = 10) -> list[dict]:
        if not self.api_key:
            return self._fallback_questions(compact_context, difficulty, count)
        prompt = (
            "Сгенерируй тестовые задания по материалу. "
            f"Сложность: {difficulty}. Количество: {count}. "
            "Ответ строго JSON-массивом объектов: "
            '[{"question":"...", "options":["...","...","...","..."], "correct_index":0, "explanation":"..."}]. '
            "Без markdown."
        )
        raw = await self._chat_json(prompt, compact_context, expect_json=True)
        try:
            data = json.loads(raw)
            valid = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                options = item.get("options", [])
                if len(options) < 4:
                    continue
                correct_index = int(item.get("correct_index", 0))
                if correct_index < 0 or correct_index >= len(options):
                    correct_index = 0
                valid.append(
                    {
                        "question": str(item.get("question", "")).strip(),
                        "options": [str(x).strip() for x in options[:5]],
                        "correct_index": correct_index,
                        "explanation": str(item.get("explanation", "")).strip(),
                    }
                )
            if len(valid) >= 3:
                return valid[:count]
        except Exception:
            log.exception("RouterAI returned invalid JSON")
        return self._fallback_questions(compact_context, difficulty, count)

    async def _chat_json(self, system_prompt: str, user_prompt: str, expect_json: bool) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:12000]},
            ],
            "temperature": 0.2,
        }
        if expect_json:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if expect_json and content.strip().startswith("{"):
                parsed = json.loads(content)
                if "questions" in parsed and isinstance(parsed["questions"], list):
                    return json.dumps(parsed["questions"], ensure_ascii=False)
            return content

    @staticmethod
    def _cheap_summary(raw_text: str) -> str:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        lines = [x for x in lines if len(x) > 2][:80]
        return "\n".join(lines)

    @staticmethod
    def _fallback_questions(compact_context: str, difficulty: str, count: int) -> list[dict]:
        snippets = [x.strip(" -•\t") for x in compact_context.splitlines() if len(x.strip()) > 8]
        if not snippets:
            snippets = ["Основы темы урока", "Практические шаги решения", "Типичные ошибки"]
        questions: list[dict] = []
        for i in range(count):
            topic = snippets[i % len(snippets)]
            answers = [
                f"Верное утверждение по теме: {topic[:60]}",
                f"Неверный частный случай для {topic[:45]}",
                "Случайный термин не по теме",
                "Противоречащее утверждение",
            ]
            random.shuffle(answers)
            correct = answers.index(next(x for x in answers if x.startswith("Верное")))
            questions.append(
                {
                    "question": f"[{difficulty}] Что корректно описывает тему: {topic[:80]}?",
                    "options": answers,
                    "correct_index": correct,
                    "explanation": "Проверьте конспект урока и выделите ключевое правило.",
                }
            )
        return questions
