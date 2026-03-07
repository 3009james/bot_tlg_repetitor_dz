from __future__ import annotations

import json
import logging
import random
import re

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
        try:
            content = await self._chat_json(prompt, raw_text, expect_json=False)
            return content.strip() or self._cheap_summary(raw_text)
        except Exception:
            log.exception("RouterAI summarize failed, using cheap summary fallback")
            return self._cheap_summary(raw_text)

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
        try:
            raw = await self._chat_json(prompt, compact_context, expect_json=True)
        except Exception:
            log.exception("RouterAI question generation failed, using fallback questions")
            return self._fallback_questions(compact_context, difficulty, count)
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

    async def extract_topics(self, compact_context: str, max_topics: int = 20) -> list[str]:
        if not compact_context.strip():
            return []
        if not self.api_key:
            return self._fallback_topics(compact_context, max_topics)
        prompt = (
            "Выдели ключевые темы урока.\n"
            f"Верни до {max_topics} тем.\n"
            'Ответ строго JSON-объектом: {"topics":["..."]}.\n'
            "Каждая тема: короткая фраза 2-7 слов, без нумерации и без пояснений."
        )
        try:
            raw = await self._chat_json(prompt, compact_context, expect_json=True)
            parsed = json.loads(raw)
            topics_raw = []
            if isinstance(parsed, dict):
                topics_raw = parsed.get("topics", [])
            elif isinstance(parsed, list):
                topics_raw = parsed
            if not isinstance(topics_raw, list):
                return self._fallback_topics(compact_context, max_topics)
            cleaned = self._normalize_topics(topics_raw, max_topics)
            if cleaned:
                return cleaned
        except Exception:
            log.exception("RouterAI topic extraction failed, using fallback topics")
        return self._fallback_topics(compact_context, max_topics)

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

    @staticmethod
    def _normalize_topics(topics_raw: list, max_topics: int) -> list[str]:
        topics: list[str] = []
        seen: set[str] = set()
        for raw in topics_raw:
            topic = str(raw or "").strip()
            topic = topic.replace("`", " ")
            topic = topic.lstrip("#> ").strip()
            topic = re.sub(r"^\d+(?:[.)]\d+)*[.)]?\s*", "", topic)
            topic = re.sub(r"\s+", " ", topic).strip().strip("-•*")
            if not topic:
                continue
            lower = topic.lower()
            if lower in {"markdown", "md", "json", "yaml", "code", "text", "текст"}:
                continue
            if "```" in topic:
                continue
            if len(topic) > 120:
                topic = topic[:120].rstrip()
            lower = topic.lower()
            if lower in seen:
                continue
            seen.add(lower)
            topics.append(topic)
            if len(topics) >= max_topics:
                break
        return topics

    @classmethod
    def _fallback_topics(cls, compact_context: str, max_topics: int) -> list[str]:
        lines = [x.strip() for x in compact_context.splitlines() if x.strip()]
        candidates = []
        for line in lines:
            line = line.strip("-•* \t")
            if not line:
                continue
            if line.startswith("```"):
                continue
            if line.lower() in {"markdown", "md"}:
                continue
            line = line.lstrip("#> ").strip()
            # Grab likely topic heading before separators if present.
            for sep in (":", "-", "—"):
                if sep in line:
                    head = line.split(sep, 1)[0].strip()
                    if 3 <= len(head) <= 90:
                        line = head
                        break
            if 3 <= len(line) <= 90:
                candidates.append(line)
            if len(candidates) >= max_topics * 3:
                break
        cleaned = cls._normalize_topics(candidates, max_topics)
        return cleaned[:max_topics]
