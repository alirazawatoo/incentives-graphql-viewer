import base64
import datetime
import io
import logging
import math
from typing import Any

import matplotlib

matplotlib.use("Agg")
import requests
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)


INCENTIVES_QUERY = """
query MyQuery {
  subnets(netUid: %d) {
    uids {
      incentive {
        uid
        data {
          value
          valueBlockNumber
          timestamp
          blockNumber
        }
      }
    }
  }
}
"""


def _build_incentives_query(subnet_uid: int) -> str:
    """
    Build the GraphQL query used to retrieve incentives for a given subnet.
    """
    return INCENTIVES_QUERY % subnet_uid


def _extract_incentives_from_response(response_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Parse the incentives GraphQL response into a normalized list of points.

    This is kept separate from network and plotting concerns so that it can
    be validated in isolation and adapted if the upstream API changes shape.
    """
    if not isinstance(response_data, dict) or response_data.get("errors"):
        return []
    data_section = response_data.get("data")
    if not isinstance(data_section, dict):
        return []
    subnets = data_section.get("subnets")
    if not isinstance(subnets, list):
        return []
    incentives = []
    for subnet in subnets:
        if not isinstance(subnet, dict):
            continue
        uids = subnet.get("uids", [])
        if isinstance(uids, dict):
            entries = uids.get("incentive", [])
        elif isinstance(uids, list):
            entries = []
            for item in uids:
                if not isinstance(item, dict):
                    continue
                nested = item.get("incentive", item)
                entries.extend(nested if isinstance(nested, list) else [nested])
        else:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            uid = entry.get("uid")
            points = entry.get("data")
            if not isinstance(uid, int) or isinstance(uid, bool) or not isinstance(points, list):
                continue
            for point in points:
                if not isinstance(point, dict):
                    continue
                try:
                    raw_value = point["value"]
                    if isinstance(raw_value, bool):
                        continue
                    value = float(raw_value)
                    if not math.isfinite(value) or value < 0:
                        continue
                    timestamp = datetime.datetime.strptime(point["timestamp"], "%Y-%m-%d:%H:%M:%S")
                except (KeyError, TypeError, ValueError):
                    continue
                incentives.append({"uid": uid, "value": value, "timestamp": timestamp})
    return sorted(incentives, key=lambda item: item["timestamp"])


def fetch_and_plot_data():
    """
    Fetch incentives data from the configured GraphQL API and return a base64-encoded PNG plot.

    Returns None if data cannot be fetched or plotted, allowing the caller to handle errors.
    """
    query = _build_incentives_query(settings.GRAPHQL_SUBNET_UID)

    try:
        response = requests.post(
            settings.GRAPHQL_API_URL,
            json={"query": query},
            timeout=getattr(settings, "GRAPHQL_REQUEST_TIMEOUT", 10),
            allow_redirects=False,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("Unable to fetch incentives data from the configured provider")
        return None

    try:
        response_data = response.json()
    except ValueError:
        logger.warning("Received non-JSON response from incentives GraphQL API")
        return None

    incentives = _extract_incentives_from_response(response_data)

    if not incentives:
        return None

    # Sort incentives by timestamp for a consistent, readable plot.
    incentives.sort(key=lambda item: item["timestamp"])

    figure = Figure(figsize=(12, 6), layout="constrained")
    axes = figure.subplots()
    grouped = {}
    for item in incentives:
        grouped.setdefault(item["uid"], []).append(item)
    for uid, points in grouped.items():
        axes.plot(
            [p["timestamp"] for p in points], [p["value"] for p in points], label=f"UID {uid}", alpha=0.8, marker="o"
        )
    axes.set(
        xlabel="Provider timestamp (timezone unspecified)",
        ylabel="Incentive value",
        title=f"Subnet {settings.GRAPHQL_SUBNET_UID}",
    )
    axes.legend(fontsize="small")
    axes.grid(True, alpha=0.2)
    axes.tick_params(axis="x", labelrotation=35)
    with io.BytesIO() as buffer:
        figure.savefig(buffer, format="png", dpi=130)
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def plot_view(request):
    graph = fetch_and_plot_data()
    if graph is None:
        return HttpResponse(
            "Unable to fetch incentives data at this time.",
            status=500,
        )
    return render(request, "plot.html", {"graph": graph, "subnet_uid": settings.GRAPHQL_SUBNET_UID})


def home_view(request):
    return render(request, "home.html")
