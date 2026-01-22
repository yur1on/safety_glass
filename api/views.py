from typing import Any, Dict, List, Tuple

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from catalog.models import Glass, GlassAlias, GlassGroup


def normalize(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def _group_payload(group: GlassGroup) -> Dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "brands": getattr(group, "brands", "") or "",
        "description": getattr(group, "description", "") or "",
        "external_id": getattr(group, "external_id", "") or "",
    }


def _brands_has_common(brands: str) -> bool:
    b = (brands or "").strip()
    if not b:
        return False
    parts = [p.strip().lower() for p in b.split(",") if p.strip()]
    return "общие" in parts


class SearchView(APIView):
    """
    GET /api/search/?q=...

    Возвращает ВСЕ АКТИВНЫЕ группы, в которых найдено совпадение по:
      - GlassAlias.normalized_alias
      - Glass.name

    Ограничение отображения 5 вариантов делаем в боте (formatter),
    но сортировку "ОБЩИЕ" делаем уже здесь (на API-уровне).
    """

    def get(self, request):
        q = request.query_params.get("q", "")
        q_stripped = (q or "").strip()
        qn = normalize(q_stripped)

        if not qn:
            return Response(
                {"detail": "Missing query param 'q'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Только активные
        alias_base = GlassAlias.objects.select_related("glass", "glass__group").filter(
            glass__is_active=True,
            glass__group__is_active=True,
        )

        glass_base = Glass.objects.select_related("group").filter(
            is_active=True,
            group__is_active=True,
        )

        # Алиасы (приоритетнее)
        alias_exact = alias_base.filter(normalized_alias=qn)
        alias_starts = alias_base.filter(normalized_alias__startswith=qn).exclude(normalized_alias=qn)
        alias_contains = (
            alias_base
            .filter(normalized_alias__icontains=qn)
            .exclude(normalized_alias=qn)
            .exclude(normalized_alias__startswith=qn)
        )

        # Название стекла
        name_exact = glass_base.filter(name__iexact=q_stripped)
        name_contains = glass_base.filter(name__icontains=q_stripped).exclude(name__iexact=q_stripped)

        # candidates: (score, group_id, matched_glass_name)
        candidates: List[Tuple[int, int, str]] = []

        for a in alias_exact:
            candidates.append((0, a.glass.group_id, a.glass.name))
        for a in alias_starts:
            candidates.append((1, a.glass.group_id, a.glass.name))
        for a in alias_contains:
            candidates.append((2, a.glass.group_id, a.glass.name))

        for g in name_exact:
            candidates.append((3, g.group_id, g.name))
        for g in name_contains:
            candidates.append((4, g.group_id, g.name))

        if not candidates:
            return Response({"found": False, "query": q_stripped}, status=status.HTTP_200_OK)

        # лучшее совпадение на группу
        best_by_group: Dict[int, Tuple[int, str]] = {}
        for score, group_id, matched_name in candidates:
            if group_id not in best_by_group or score < best_by_group[group_id][0]:
                best_by_group[group_id] = (score, matched_name)

        # подтянуть группы
        group_ids = list(best_by_group.keys())
        groups = (
            GlassGroup.objects
            .filter(id__in=group_ids, is_active=True)
            .prefetch_related("glasses")
        )
        groups_by_id = {g.id: g for g in groups}

        # сортировка:
        # 1) бренды содержат "ОБЩИЕ" -> первыми
        # 2) score
        # 3) id
        def _sort_gid(gid: int):
            grp = groups_by_id.get(gid)
            brands = (getattr(grp, "brands", "") or "") if grp else ""
            is_common = _brands_has_common(brands)
            score = best_by_group[gid][0]
            return (0 if is_common else 1, score, gid)

        group_ids_sorted = sorted(
            [gid for gid in group_ids if gid in groups_by_id],
            key=_sort_gid
        )

        results: List[Dict[str, Any]] = []
        for gid in group_ids_sorted:
            group = groups_by_id.get(gid)
            if not group:
                continue

            compatible = list(
                group.glasses
                .filter(is_active=True)
                .order_by("name")
                .values_list("name", flat=True)
            )

            results.append({
                "matched_glass": best_by_group[gid][1],
                "group": _group_payload(group),
                "compatible_glasses": compatible,
            })

        if not results:
            return Response({"found": False, "query": q_stripped}, status=status.HTTP_200_OK)

        return Response(
            {"found": True, "query": q_stripped, "results": results},
            status=status.HTTP_200_OK
        )
