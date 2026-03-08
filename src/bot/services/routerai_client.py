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
            "Формат: ключевые темы, важные правила, типичные ошибки, 10-20 тезисов. "
            "Пиши по-русски, без воды."
        )
        try:
            content = await self._chat_json(prompt, raw_text, expect_json=False)
            return content.strip() or self._cheap_summary(raw_text)
        except Exception:
            log.exception("RouterAI summarize failed, using cheap summary fallback")
            return self._cheap_summary(raw_text)

    async def generate_questions(
        self,
        compact_context: str,
        difficulty: str,
        count: int = 10,
        lesson_type_slug: str = "",
        selected_topics: list[str] | None = None,
    ) -> list[dict]:
        topics = [str(x).strip() for x in (selected_topics or []) if str(x).strip()]
        if not self.api_key:
            return self._fallback_questions(compact_context, difficulty, count, lesson_type_slug, topics)

        prompt = self._build_generation_prompt(
            difficulty=difficulty,
            count=count,
            lesson_type_slug=lesson_type_slug,
            selected_topics=topics,
        )
        user_payload = compact_context
        if topics:
            user_payload = "Выбранные темы:\n- " + "\n- ".join(topics[:15]) + "\n\nМатериалы:\n" + compact_context
        try:
            raw = await self._chat_json(prompt, user_payload, expect_json=True, timeout_sec=180)
            parsed = self._parse_generated_questions(
                raw,
                count=count,
                lesson_type_slug=lesson_type_slug,
                selected_topics=topics,
            )
            if len(parsed) >= count:
                return parsed[:count]
            strict_prompt = prompt + "\nВажно: запрет на однословные или общие формулировки. Каждый вопрос должен быть самодостаточным."
            raw_retry = await self._chat_json(strict_prompt, user_payload, expect_json=True, timeout_sec=180)
            parsed_retry = self._parse_generated_questions(
                raw_retry,
                count=count,
                lesson_type_slug=lesson_type_slug,
                selected_topics=topics,
            )
            if len(parsed_retry) >= count:
                return parsed_retry[:count]
        except Exception:
            log.exception("RouterAI question generation failed, using fallback questions")
        return self._fallback_questions(compact_context, difficulty, count, lesson_type_slug, topics)

    async def evaluate_code_solution(
        self,
        *,
        question_text: str,
        student_code: str,
        reference_solution: str,
        language: str,
        difficulty: str,
    ) -> dict:
        if not student_code.strip():
            return {
                "is_correct": False,
                "feedback": "Код пустой. Добавьте решение и отправьте на проверку.",
                "suggested_code": reference_solution.strip(),
            }
        if not self.api_key:
            return self._fallback_code_review(student_code, reference_solution)

        prompt = (
            "Проверь решение студента.\n"
            "Верни строго JSON-объект:\n"
            '{"is_correct":true|false,"feedback":"...","suggested_code":"..."}\n'
            "Правила:\n"
            "- Учитывай условие задачи, корректность и граничные случаи.\n"
            "- feedback: 2-5 коротких предложений с рекомендациями.\n"
            "- suggested_code: корректное эталонное решение на том же языке.\n"
            "- Без markdown."
        )
        user_payload = (
            f"Язык: {language}\n"
            f"Сложность: {difficulty}\n"
            f"Задание:\n{question_text[:2500]}\n\n"
            f"Код ученика:\n{student_code[:6000]}\n\n"
            f"Эталон (для проверки):\n{reference_solution[:4000]}"
        )
        try:
            raw = await self._chat_json(prompt, user_payload, expect_json=True, timeout_sec=120)
            data = json.loads(raw)
            is_correct = bool(data.get("is_correct", False))
            feedback = str(data.get("feedback", "")).strip() or "Проверка завершена."
            suggested = str(data.get("suggested_code", "")).strip() or reference_solution.strip()
            return {
                "is_correct": is_correct,
                "feedback": feedback[:3000],
                "suggested_code": suggested[:10000],
            }
        except Exception:
            log.exception("RouterAI code evaluation failed, using fallback")
            return self._fallback_code_review(student_code, reference_solution)

    async def extract_topics(self, compact_context: str, max_topics: int = 20) -> list[str]:
        if not compact_context.strip():
            return []
        if not self.api_key:
            return self._fallback_topics(compact_context, max_topics)
        prompt = (
            "Выдели ключевые темы урока.\n"
            f"Верни до {max_topics} тем.\n"
            'Ответ строго JSON-объектом: {"topics":["..."]}.\n'
            "Каждая тема: короткая фраза 2-7 слов, без нумерации и пояснений."
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

    def _build_generation_prompt(
        self,
        *,
        difficulty: str,
        count: int,
        lesson_type_slug: str,
        selected_topics: list[str],
    ) -> str:
        slug = (lesson_type_slug or "").strip().lower()
        topics_block = ""
        if selected_topics:
            topics_block = "Обязательные темы (вопросы должны опираться на них):\n- " + "\n- ".join(selected_topics[:15]) + "\n"
        if slug in {"cpp", "python"}:
            lang = "C++" if slug == "cpp" else "Python"
            return (
                "Сгенерируй качественный набор заданий строго по предоставленным материалам.\n"
                f"Предмет: {lang}. Сложность: {difficulty}. Количество: {count}.\n"
                + topics_block +
                "Нужно ровно 10 заданий:\n"
                "- 3 задания типа mcq (теория, 4-5 вариантов, один верный).\n"
                "- 7 заданий типа code (практика, написать программу).\n"
                "Для каждого code-вопроса формулировка должна начинаться со слов: «Напишите программу, ...».\n"
                "Запрещены короткие/общие вопросы вроде «C++», «Python», «что такое цикл?» без контекста.\n"
                "Каждый вопрос должен быть самодостаточным и конкретным.\n"
                "Верни строго JSON-массив объектов.\n"
                "Формат объекта:\n"
                '{"type":"mcq","question":"...","options":["..."],"correct_index":0,"explanation":"..."}\n'
                "или\n"
                '{"type":"code","question":"Напишите программу, ...","explanation":"...","meta":{"language":"python|cpp","reference_solution":"..."}}\n'
                "Без markdown, без пояснительного текста."
            )
        return (
            "Сгенерируй качественный набор заданий строго по материалам.\n"
            f"Предмет: математика. Сложность: {difficulty}. Количество: {count}.\n"
            + topics_block +
            "Нужно ровно 10 заданий типа mcq:\n"
            "- 3 теоретических.\n"
            "- 7 практических задач с вариантами ответа.\n"
            "Запрещены однословные и общие вопросы без условия.\n"
            "Верни строго JSON-массив объектов формата:\n"
            '{"type":"mcq","question":"...","options":["..."],"correct_index":0,"explanation":"пошаговое решение"}\n'
            "Без markdown."
        )

    async def _chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        expect_json: bool,
        timeout_sec: int = 60,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:14000]},
            ],
            "temperature": 0.2,
        }
        if expect_json:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if expect_json and content.strip().startswith("{"):
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    if "questions" in parsed and isinstance(parsed["questions"], list):
                        return json.dumps(parsed["questions"], ensure_ascii=False)
                    if "items" in parsed and isinstance(parsed["items"], list):
                        return json.dumps(parsed["items"], ensure_ascii=False)
            return content

    def _parse_generated_questions(
        self,
        raw: str,
        *,
        count: int,
        lesson_type_slug: str,
        selected_topics: list[str],
    ) -> list[dict]:
        data = json.loads(raw)
        if isinstance(data, dict):
            if isinstance(data.get("questions"), list):
                data = data["questions"]
            elif isinstance(data.get("items"), list):
                data = data["items"]
            else:
                data = []
        if not isinstance(data, list):
            return []

        parsed: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            q_type = str(item.get("type", "mcq")).strip().lower()
            question = str(item.get("question", "")).strip()
            explanation = str(item.get("explanation", "")).strip()
            if not question:
                continue
            if q_type == "code":
                meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                language = str(meta.get("language", "")).strip().lower()
                if language not in {"python", "cpp"}:
                    language = "cpp" if lesson_type_slug == "cpp" else "python"
                reference = str(meta.get("reference_solution", "")).strip()
                if not reference:
                    continue
                question = self._normalize_code_question(question)
                if self._is_low_quality_question(question, selected_topics):
                    continue
                parsed.append(
                    {
                        "type": "code",
                        "question": question,
                        "options": [],
                        "correct_index": -1,
                        "explanation": explanation or "Сверьте код с эталонным решением.",
                        "meta": {
                            "language": language,
                            "reference_solution": reference,
                        },
                    }
                )
                continue

            options = item.get("options", [])
            if not isinstance(options, list):
                continue
            options = [str(x).strip() for x in options if str(x).strip()][:5]
            if len(options) < 4:
                continue
            if self._is_low_quality_question(question, selected_topics):
                continue
            correct_index = int(item.get("correct_index", 0))
            if correct_index < 0 or correct_index >= len(options):
                correct_index = 0
            parsed.append(
                {
                    "type": "mcq",
                    "question": question,
                    "options": options,
                    "correct_index": correct_index,
                    "explanation": explanation,
                    "meta": {},
                }
            )
        return parsed[:count]

    @staticmethod
    def _normalize_code_question(question: str) -> str:
        q = question.strip()
        if not q:
            return q
        lower = q.lower()
        if lower.startswith("напишите программу"):
            return q
        if lower.startswith("написать программу"):
            return "Напишите программу" + q[len("написать программу") :]
        if lower.startswith("реализуйте"):
            return "Напишите программу, " + q[10:].lstrip(" ,")
        return "Напишите программу, которая " + q[0].lower() + q[1:]

    @classmethod
    def _is_low_quality_question(cls, question: str, selected_topics: list[str]) -> bool:
        q = (question or "").strip()
        if len(q) < 24:
            return True
        words = re.findall(r"[A-Za-zА-Яа-я0-9_+#]{2,}", q.lower())
        if len(words) < 5:
            return True
        bad_exact = {
            "c++",
            "cpp",
            "python",
            "математика",
            "вопрос",
            "теория",
            "практика",
        }
        if q.lower() in bad_exact:
            return True
        if selected_topics:
            topic_words: set[str] = set()
            for topic in selected_topics[:20]:
                for w in re.findall(r"[A-Za-zА-Яа-я0-9_+#]{3,}", topic.lower()):
                    topic_words.add(w)
            if topic_words and not any(w in topic_words for w in words) and len(words) < 12:
                return True
        return False

    @staticmethod
    def _cheap_summary(raw_text: str) -> str:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        lines = [x for x in lines if len(x) > 2][:80]
        return "\n".join(lines)

    @staticmethod
    def _fallback_code_review(student_code: str, reference_solution: str) -> dict:
        student_len = len(student_code.strip())
        ref = reference_solution.strip()
        if student_len < 20:
            return {
                "is_correct": False,
                "feedback": "Решение слишком короткое. Добавьте полноценный алгоритм и повторите проверку.",
                "suggested_code": ref,
            }
        return {
            "is_correct": False,
            "feedback": "Проверка через LLM недоступна. Ниже эталонный вариант для сравнения.",
            "suggested_code": ref,
        }

    @staticmethod
    def _fallback_questions(
        compact_context: str,
        difficulty: str,
        count: int,
        lesson_type_slug: str,
        selected_topics: list[str],
    ) -> list[dict]:
        snippets = [x.strip(" -•\t") for x in compact_context.splitlines() if len(x.strip()) > 15]
        snippets = [x for x in snippets if len(x.split()) >= 3]
        if selected_topics:
            snippets = selected_topics + snippets
        if not snippets:
            snippets = ["Основы темы урока", "Практические шаги решения", "Типичные ошибки"]

        slug = (lesson_type_slug or "").strip().lower()
        items: list[dict] = []
        if slug in {"cpp", "python"}:
            lang = "cpp" if slug == "cpp" else "python"
            for i in range(min(3, count)):
                topic = snippets[i % len(snippets)]
                options = [
                    f"Корректный вариант по теме {topic[:45]}",
                    "Неверное утверждение с типичной ошибкой",
                    "Логически неверная конструкция",
                    "Несвязанный вариант ответа",
                ]
                random.shuffle(options)
                correct = 0
                for idx, opt in enumerate(options):
                    if opt.startswith("Корректный"):
                        correct = idx
                        break
                items.append(
                    {
                        "type": "mcq",
                        "question": f"[{difficulty}] Теория: {topic[:80]}",
                        "options": options,
                        "correct_index": correct,
                        "explanation": "Опирайтесь на определения и базовые правила темы.",
                        "meta": {},
                    }
                )
            for i in range(3, count):
                topic = snippets[i % len(snippets)]
                items.append(
                    {
                        "type": "code",
                        "question": f"Напишите программу, которая решает задачу по теме «{topic[:80]}».",
                        "options": [],
                        "correct_index": -1,
                        "explanation": "Проверьте корректность на граничных случаях.",
                        "meta": {
                            "language": lang,
                            "reference_solution": self_or_default_solution(lang),
                        },
                    }
                )
            return items[:count]

        for i in range(count):
            topic = snippets[i % len(snippets)]
            options = [
                f"Правильное решение по теме {topic[:45]}",
                "Типичная ошибка в вычислениях",
                "Неверный выбор формулы",
                "Неполное решение без проверки",
            ]
            random.shuffle(options)
            correct = 0
            for idx, opt in enumerate(options):
                if opt.startswith("Правильное"):
                    correct = idx
                    break
            items.append(
                {
                    "type": "mcq",
                    "question": f"[{difficulty}] Выберите верное решение для задачи по теме «{topic[:90]}».",
                    "options": options,
                    "correct_index": correct,
                    "explanation": "Сверьте решение с формулой и проверкой результата.",
                    "meta": {},
                }
            )
        return items[:count]

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


def self_or_default_solution(language: str) -> str:
    if language == "cpp":
        return (
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n"
            "int main() {\n"
            "    ios::sync_with_stdio(false);\n"
            "    cin.tie(nullptr);\n"
            "    // TODO: реализуйте решение\n"
            "    return 0;\n"
            "}\n"
        )
    return (
        "def solve():\n"
        "    # TODO: реализуйте решение\n"
        "    pass\n\n"
        "if __name__ == '__main__':\n"
        "    solve()\n"
    )
