"""Fetch and normalise subnet incentive history from the GraphQL provider."""

import datetime
import json
import logging
import math
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%d:%H:%M:%S"

# netUid is validated as an int before interpolation, so the query cannot be
# altered by user input. Variables are not used because the provider's
# argument type has not been checked against its schema.
INCENTIVES_QUERY = """
query SubnetIncentives {
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


class ProviderError(Exception):
    """The provider could not be reached or sent something we cannot use."""


def build_incentives_query(subnet_uid: int) -> str:
    return INCENTIVES_QUERY % int(subnet_uid)


def extract_incentives(response_data: Any) -> list[dict[str, Any]]:
    """Return valid points as ``{"uid", "value", "timestamp"}`` dicts sorted by time.

    Accepts the nested ``uids[].incentive`` shape the query asks for and the
    older flattened ``uids[]`` shape. Anything malformed is skipped rather than
    failing the whole chart.
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
        for entry in _incentive_entries(subnet.get("uids", [])):
            uid = entry.get("uid")
            points = entry.get("data")
            if not isinstance(uid, int) or isinstance(uid, bool) or not isinstance(points, list):
                continue
            for point in points:
                parsed = _parse_point(point)
                if parsed is not None:
                    incentives.append({"uid": uid, "value": parsed[0], "timestamp": parsed[1]})
    return sorted(incentives, key=lambda item: item["timestamp"])


def _incentive_entries(uids: Any) -> list[dict[str, Any]]:
    if isinstance(uids, dict):
        nested = uids.get("incentive", [])
        return [entry for entry in nested if isinstance(entry, dict)] if isinstance(nested, list) else []
    if not isinstance(uids, list):
        return []
    entries = []
    for item in uids:
        if not isinstance(item, dict):
            continue
        nested = item.get("incentive", item)
        entries.extend(entry for entry in (nested if isinstance(nested, list) else [nested]) if isinstance(entry, dict))
    return entries


def _parse_point(point: Any) -> tuple[float, datetime.datetime] | None:
    if not isinstance(point, dict):
        return None
    raw_value = point.get("value")
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        value = float(raw_value)
        timestamp = datetime.datetime.strptime(point["timestamp"], TIMESTAMP_FORMAT)
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value, timestamp


def _read_capped_body(response: requests.Response, limit: int) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ProviderError("The provider response is larger than this app accepts.")
    body = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        body.extend(chunk)
        if len(body) > limit:
            raise ProviderError("The provider response is larger than this app accepts.")
    return bytes(body)


def fetch_incentives(subnet_uid: int) -> list[dict[str, Any]]:
    """POST the incentives query and return parsed points (possibly empty).

    Raises ProviderError when the provider is unreachable, answers with a
    non-200 status (redirects are not followed), sends oversized or non-JSON
    bodies, or reports GraphQL errors.
    """
    try:
        with requests.post(
            settings.GRAPHQL_API_URL,
            json={"query": build_incentives_query(subnet_uid)},
            timeout=settings.GRAPHQL_REQUEST_TIMEOUT,
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                logger.warning("Incentives provider answered HTTP %s", response.status_code)
                raise ProviderError(f"The provider answered with HTTP {response.status_code}.")
            body = _read_capped_body(response, settings.GRAPHQL_MAX_RESPONSE_BYTES)
    except requests.Timeout as exc:
        logger.warning("Incentives provider timed out")
        raise ProviderError("The provider did not answer in time.") from exc
    except requests.RequestException as exc:
        logger.warning("Incentives provider request failed: %s", type(exc).__name__)
        raise ProviderError("The provider could not be reached.") from exc

    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise ProviderError("The provider sent a response that is not JSON.") from exc
    if isinstance(payload, dict) and payload.get("errors"):
        raise ProviderError("The provider reported an error for this query.")
    return extract_incentives(payload)
