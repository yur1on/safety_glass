from typing import Any, Dict, List


def _safe(s: Any) -> str:
    return (s or "").strip() if isinstance(s, str) else ""


def _brands_has_common(brands: str) -> bool:
    """
    True, если в строке брендов есть 'ОБЩИЕ' (регистронезависимо),
    поддерживает список через запятую.
    """
    b = (brands or "").strip()
    if not b:
        return False
    parts = [p.strip().lower() for p in b.split(",") if p.strip()]
    return "общие" in parts


def format_search_result(data: Dict[str, Any], *, is_premium: bool, free_glasses_limit: int = 3) -> str:
    """
    FREE:
      - показывает первые free_glasses_limit стекла в каждом варианте
      - пишет, сколько ещё стекол скрыто
      - добавляет призыв оформить premium

    PREMIUM:
      - показывает все стекла
    """
    if not data.get("found"):
        q = _safe(data.get("query"))
        q_part = f"🔎 Запрос: <b>{q}</b>\n\n" if q else ""
        return (
            "❌ <b>Совпадений не найдено</b>\n\n"
            f"{q_part}"
            "Что можно сделать:\n"
            "• попробуйте другое написание (например: <b>Redmi 9A</b>)\n"
        )

    results: List[Dict[str, Any]] = data.get("results") or []

    # На случай старого формата (один результат без results)
    if not results:
        group = data.get("group") or {}
        results = [{
            "matched_glass": data.get("matched_glass", ""),
            "group": group,
            "compatible_glasses": data.get("compatible_glasses", []),
        }]

    # Сортировка: "ОБЩИЕ" всегда первыми
    def sort_key(item: Dict[str, Any]):
        group = item.get("group") or {}
        brands = _safe(group.get("brands"))
        is_common = _brands_has_common(brands)
        return (0 if is_common else 1,)

    results = sorted(results, key=sort_key)

    max_groups = 5
    shown_groups = results[:max_groups]
    remainder_groups = max(0, len(results) - len(shown_groups))

    blocks: List[str] = []
    blocks.append("✅ <b>Взаимозаменяемость стекла</b>")

    if not is_premium:
        blocks.append(
            "Чтобы видеть полный список подключите — /premium"
        )

    for idx, item in enumerate(shown_groups, start=1):
        matched = _safe(item.get("matched_glass"))
        group = item.get("group") or {}
        brands = _safe(group.get("brands"))
        description = _safe(group.get("description"))

        glasses: List[str] = item.get("compatible_glasses") or []
        glasses = [g.strip() for g in glasses if isinstance(g, str) and g.strip()]

        # Уникализируем список стёкол
        seen = set()
        uniq: List[str] = []
        for g in glasses:
            if g not in seen:
                seen.add(g)
                uniq.append(g)

        if is_premium:
            shown_items = uniq
            rest_items = 0
        else:
            shown_items = uniq[:max(0, int(free_glasses_limit))]
            rest_items = max(0, len(uniq) - len(shown_items))

        lines = [f"• {g}" for g in shown_items] if shown_items else ["• (пусто)"]

        if not is_premium and rest_items > 0:
            lines.append(f"🔒 Ещё <b>{rest_items}</b> стекол скрыто.")

        block = []
        block.append(f"\n<b>Вариант {idx}</b>")
        if matched:
            block.append(f"🔖 Найдено: <b>{matched}</b>")
        if brands:
            block.append(f"🏷 Бренд: <b>{brands}</b>")
        if description:
            desc = description
            if len(desc) > 300:
                desc = desc[:297].rstrip() + "…"
            block.append(f"📝 Описание: {desc}")

        block.append("📌 <b>Подходящие стёкла:</b>")
        block.extend(lines)

        blocks.append("\n".join(block))

    if remainder_groups > 0:
        blocks.append(
            f"\nℹ️ Показано <b>{len(shown_groups)}</b> из <b>{len(results)}</b>. "
            f"Ещё вариантов: <b>{remainder_groups}</b>. Уточните запрос, если нужно."
        )

    return "\n".join(blocks).strip()
