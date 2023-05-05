# Incentives GraphQL Viewer

A Django application that queries time-series incentive values from a GraphQL endpoint and renders a server-generated Matplotlib chart grouped by UID.

## Processing flow

```text
configured subnet UID -> GraphQL request -> normalize incentive points
                                        -> sort by timestamp
                                        -> plot one series per UID
                                        -> embed base64 PNG in Django page
```

Malformed points are skipped, network/JSON failures produce an unavailable response, and each UID is charted independently.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

Configure `GRAPHQL_API_URL`, `GRAPHQL_SUBNET_UID`, and optionally the request timeout in Django settings or the environment contract used by the project.

Open `http://127.0.0.1:8000/` and follow the graph link.

## Boundaries

- The historical hosted URL is not treated as a verified deployment.
- Graph generation is synchronous and memory-backed; large responses can increase request latency and image size.
- Timestamp parsing expects `%Y-%m-%d:%H:%M:%S`.
- The upstream API, Django application, and tests were not run during the portfolio review.
