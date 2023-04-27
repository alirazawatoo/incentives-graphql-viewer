"""Offline stand-in for the incentives GraphQL endpoint, serving synthetic data.

Run it and point GRAPHQL_API_URL at http://127.0.0.1:8765/graphql to use the
site without touching the real provider. Subnet 0 returns an empty series and
subnet 9999 returns HTTP 503, so the empty and error states can be seen too.
Only the standard library is used.
"""

import argparse
import datetime
import json
import math
import random
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EMPTY_SUBNET = 0
FAILING_SUBNET = 9999
UID_COUNT = 16
HOURS = 72
START = datetime.datetime(2024, 3, 1, 0, 0, 0)


def synthetic_subnet(net_uid: int) -> dict:
    rng = random.Random(net_uid)
    uids = []
    for uid in range(UID_COUNT):
        level = rng.uniform(0.002, 0.06)
        phase = rng.uniform(0, math.tau)
        drift = rng.uniform(-0.25, 0.35)
        data = []
        for hour in range(HOURS):
            wave = 1 + 0.18 * math.sin(phase + hour / 9) + drift * hour / HOURS
            value = max(level * wave + rng.gauss(0, level * 0.03), 0)
            timestamp = (START + datetime.timedelta(hours=hour)).strftime("%Y-%m-%d:%H:%M:%S")
            data.append({"value": f"{value:.6f}", "timestamp": timestamp, "blockNumber": 2_400_000 + hour * 300})
        uids.append({"incentive": {"uid": uid, "data": data}})
    return {"data": {"subnets": [{"uids": uids}]}}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        try:
            query = json.loads(self.rfile.read(length))["query"]
            net_uid = int(re.search(r"netUid:\s*(\d+)", query).group(1))
        except (ValueError, KeyError, TypeError, AttributeError):
            return self.send_json(400, {"errors": [{"message": "Expected a subnets(netUid: N) query"}]})
        if net_uid == FAILING_SUBNET:
            return self.send_json(503, {"errors": [{"message": "Synthetic outage"}]})
        if net_uid == EMPTY_SUBNET:
            return self.send_json(200, {"data": {"subnets": []}})
        return self.send_json(200, synthetic_subnet(net_uid))

    def send_json(self, status: int, body: dict):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Synthetic provider on http://{args.host}:{args.port}/graphql", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
