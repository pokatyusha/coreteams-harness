# Проверка поставки

Проверено 27.10.2026 (Europe/Moscow), перед начальной публикацией:

- `python scripts/validate.py` — PASS: локальная структура, профили, ручной режим, отсутствие workflows, примеры сообщений.
- `python -m unittest discover -s tests -v` — 17 PASS, 0 FAIL. Включены неверный адресат, подмена request/harness/source SHA, выход scope за относительные пути, запрет merge/deploy/background и продуктовых действий при connection_check, обязательные ограничения и доказательства результата.
- `python scripts/validate.py --message templates/result.json --request templates/request.json` — PASS: синтетический round trip.
- Штатный `skill-creator/scripts/quick_validate.py .agents/skills/coreteams-repository-handoff` — PASS (`Skill is valid!`). PyYAML использован только из игнорируемой локальной папки инструмента; пакет обвязки не требует сторонних зависимостей.
- `git diff --cached --check` — PASS.

Форматный валидатор не проверяет подлинность GitHub-автора, права, существование удалённых SHA, последовательность событий, exactly-once или совместимость продукта. Эти проверки выполняются по протоколу при ручной обработке реального Issue. Примеры содержат синтетические SHA/время/URL, не доказательства выполнения.

Live connection_check с обвязками Арины, Филиппа и Димы: NOT_RUN. Доступ и локальные привязки участники ещё не подтвердили. Продуктовые контрактные тесты, deploy и настоящий E2E не входят в создание этой обвязки и не запускались.
