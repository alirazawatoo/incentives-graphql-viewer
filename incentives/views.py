from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render
from django.utils import timezone

from .charts import MAX_PLOTTED_UIDS, plotted_rows, render_chart_base64, summarise
from .forms import SubnetForm
from .provider import ProviderError, fetch_incentives


def load_chart(subnet_uid: int) -> tuple[dict, bool]:
    """Return ``(chart, from_cache)``. Successful fetches, empty ones included, are cached."""
    key = f"incentives:chart:{subnet_uid}"
    chart = cache.get(key)
    if chart is not None:
        return chart, True
    points = fetch_incentives(subnet_uid)
    summary = summarise(points)
    chart = {
        "graph": render_chart_base64(points, subnet_uid) if points else None,
        "plotted": plotted_rows(summary["ranked"]),
        "uid_count": summary["uid_count"],
        "point_count": summary["point_count"],
        "first": summary["first"],
        "last": summary["last"],
        "fetched_at": timezone.now(),
    }
    cache.set(key, chart, settings.GRAPHQL_CACHE_SECONDS)
    return chart, False


def _page_context() -> dict:
    return {
        "default_subnet": settings.GRAPHQL_SUBNET_UID,
        "max_plotted": MAX_PLOTTED_UIDS,
        "cache_seconds": settings.GRAPHQL_CACHE_SECONDS,
        "timeout": settings.GRAPHQL_REQUEST_TIMEOUT,
    }


def plot_view(request):
    form = SubnetForm({"subnet": request.GET.get("subnet", settings.GRAPHQL_SUBNET_UID)})
    context = {"form": form, **_page_context()}
    if not form.is_valid():
        return render(request, "plot.html", {**context, "state": "invalid"}, status=400)

    subnet_uid = form.cleaned_data["subnet"]
    context["subnet_uid"] = subnet_uid
    try:
        chart, from_cache = load_chart(subnet_uid)
    except ProviderError as exc:
        return render(request, "plot.html", {**context, "state": "error", "error_message": str(exc)}, status=502)

    state = "chart" if chart["graph"] else "empty"
    return render(request, "plot.html", {**context, **chart, "state": state, "from_cache": from_cache})


def home_view(request):
    form = SubnetForm(initial={"subnet": settings.GRAPHQL_SUBNET_UID})
    return render(request, "home.html", {"form": form, **_page_context()})
