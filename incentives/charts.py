"""Render incentive series to PNG with a per-call Figure (no shared pyplot state)."""

import base64
import io
from typing import Any

import matplotlib

matplotlib.use("Agg")

from matplotlib.dates import AutoDateLocator, ConciseDateFormatter  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

# A full subnet has up to 256 UIDs; beyond a dozen lines the legend and the
# chart stop being readable, so only the highest earners are drawn.
MAX_PLOTTED_UIDS = 12

INK = "#1f2a24"
GRID = "#d9d3c4"
SERIES_COLOURS = [
    "#0f6b5c",
    "#c2571a",
    "#3a5a8c",
    "#8a6d1d",
    "#7a3b5e",
    "#2f7d32",
    "#a23b2a",
    "#4b6b6b",
    "#b07d2b",
    "#5b4a8a",
    "#1f5f7a",
    "#6b6b2f",
]


def summarise(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Group points by UID and rank UIDs by their latest value (highest first)."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for point in points:
        grouped.setdefault(point["uid"], []).append(point)
    ranked = sorted(
        ({"uid": uid, "latest": series[-1]["value"], "samples": len(series)} for uid, series in grouped.items()),
        key=lambda row: (-row["latest"], row["uid"]),
    )
    return {
        "grouped": grouped,
        "ranked": ranked,
        "uid_count": len(grouped),
        "point_count": len(points),
        "first": points[0]["timestamp"] if points else None,
        "last": points[-1]["timestamp"] if points else None,
    }


def plotted_rows(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The UIDs that get a line, each with the colour used for it."""
    return [{**row, "colour": colour} for row, colour in zip(ranked[:MAX_PLOTTED_UIDS], SERIES_COLOURS, strict=False)]


def render_chart_png(points: list[dict[str, Any]], subnet_uid: int) -> bytes:
    summary = summarise(points)
    figure = Figure(figsize=(12, 6), layout="constrained", facecolor="white")
    axes = figure.subplots()
    for row in plotted_rows(summary["ranked"]):
        series = summary["grouped"][row["uid"]]
        colour = row["colour"]
        axes.plot(
            [p["timestamp"] for p in series],
            [p["value"] for p in series],
            label=f"UID {row['uid']}",
            color=colour,
            linewidth=1.8,
            marker="o",
            markersize=3,
        )
    locator = AutoDateLocator()
    axes.xaxis.set_major_locator(locator)
    axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    axes.set_xlabel("Provider timestamp (timezone not stated by the provider)", color=INK)
    axes.set_ylabel("Incentive value", color=INK)
    axes.set_title(f"Subnet {subnet_uid}", loc="left", color=INK, fontsize=14, fontweight="bold")
    axes.grid(True, color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    axes.tick_params(colors=INK)
    axes.legend(fontsize="small", frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    with io.BytesIO() as buffer:
        figure.savefig(buffer, format="png", dpi=110)
        return buffer.getvalue()


def render_chart_base64(points: list[dict[str, Any]], subnet_uid: int) -> str:
    return base64.b64encode(render_chart_png(points, subnet_uid)).decode("ascii")
