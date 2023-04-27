import json
import os
import runpy
import threading
from pathlib import Path
from unittest.mock import patch

import requests
import responses
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from incentives.charts import MAX_PLOTTED_UIDS, render_chart_png, summarise
from incentives.provider import ProviderError, build_incentives_query, extract_incentives, fetch_incentives

API_URL = "https://provider.test/graphql"


def payload(*uids, points_per_uid=3, base=10.0):
    """Synthetic provider response in the nested shape the query requests."""
    return {
        "data": {
            "subnets": [
                {
                    "uids": [
                        {
                            "incentive": {
                                "uid": uid,
                                "data": [
                                    {"value": str(base + uid + hour), "timestamp": f"2024-01-01:{hour:02d}:00:00"}
                                    for hour in range(points_per_uid)
                                ],
                            }
                        }
                        for uid in uids
                    ]
                }
            ]
        }
    }


class ExtractIncentivesTests(SimpleTestCase):
    def test_flattened_legacy_shape(self):
        response_data = {
            "data": {
                "subnets": [
                    {
                        "uids": [
                            {
                                "uid": 1,
                                "data": [
                                    {"value": "15.0", "timestamp": "2024-01-01:13:00:00"},
                                    {"value": "10.5", "timestamp": "2024-01-01:12:00:00"},
                                ],
                            }
                        ]
                    }
                ]
            }
        }

        incentives = extract_incentives(response_data)

        self.assertEqual([p["value"] for p in incentives], [10.5, 15.0])
        self.assertEqual(incentives[0]["uid"], 1)

    def test_malformed_points_are_skipped(self):
        points = [
            {"timestamp": "2024-01-01:12:00:00"},
            {"value": "not-a-number", "timestamp": "2024-01-01:12:00:00"},
            {"value": "5.0"},
            {"value": "5.0", "timestamp": "2024-01-01T12:00:00Z"},
            {"value": "5.0", "timestamp": "2024-01-01:12:00:00"},
            "junk",
        ]
        incentives = extract_incentives({"data": {"subnets": [{"uids": [{"uid": 2, "data": points}]}]}})

        self.assertEqual(incentives, [{"uid": 2, "value": 5.0, "timestamp": incentives[0]["timestamp"]}])

    def test_non_finite_negative_and_boolean_values_are_dropped(self):
        points = [{"value": v, "timestamp": "2024-01-01:12:00:00"} for v in ["NaN", "Infinity", -1, True, None, 2.5]]
        parsed = extract_incentives({"data": {"subnets": [{"uids": [{"incentive": {"uid": 3, "data": points}}]}]}})

        self.assertEqual([p["value"] for p in parsed], [2.5])

    def test_bad_uids_are_dropped(self):
        uids = [
            {"incentive": {"uid": uid, "data": [{"value": 1, "timestamp": "2024-01-01:12:00:00"}]}}
            for uid in [True, "4", None, 5]
        ]
        parsed = extract_incentives({"data": {"subnets": [{"uids": uids}]}})

        self.assertEqual([p["uid"] for p in parsed], [5])

    def test_bad_containers_and_graphql_errors_are_empty(self):
        for response_data in [None, [], {"data": []}, {"data": {"subnets": [None]}}, {"errors": [{"message": "x"}]}]:
            self.assertEqual(extract_incentives(response_data), [])

    def test_query_embeds_only_an_integer(self):
        self.assertIn("subnets(netUid: 42)", build_incentives_query(42))
        with self.assertRaises(ValueError):
            build_incentives_query("1) { __schema")


@override_settings(GRAPHQL_API_URL=API_URL, GRAPHQL_REQUEST_TIMEOUT=2, GRAPHQL_MAX_RESPONSE_BYTES=50_000)
class FetchIncentivesTests(SimpleTestCase):
    @responses.activate
    def test_success_posts_query_for_subnet(self):
        responses.post(API_URL, json=payload(1, 2))

        points = fetch_incentives(7)

        self.assertEqual(len(points), 6)
        sent = json.loads(responses.calls[0].request.body)
        self.assertIn("subnets(netUid: 7)", sent["query"])

    @responses.activate
    def test_connection_error_raises_provider_error(self):
        responses.post(API_URL, body=requests.ConnectionError("down"))

        with self.assertRaisesMessage(ProviderError, "could not be reached"):
            fetch_incentives(18)

    @responses.activate
    def test_timeout_raises_provider_error(self):
        responses.post(API_URL, body=requests.ReadTimeout("slow"))

        with self.assertRaisesMessage(ProviderError, "did not answer in time"):
            fetch_incentives(18)

    @responses.activate
    def test_server_error_status_raises(self):
        responses.post(API_URL, status=503, json={"message": "maintenance"})

        with self.assertRaisesMessage(ProviderError, "HTTP 503"):
            fetch_incentives(18)

    @responses.activate
    def test_redirect_is_not_followed(self):
        responses.post(API_URL, status=302, headers={"Location": "https://elsewhere.test/"})

        with self.assertRaisesMessage(ProviderError, "HTTP 302"):
            fetch_incentives(18)
        self.assertEqual(len(responses.calls), 1)

    @responses.activate
    def test_non_json_body_raises(self):
        responses.post(API_URL, body="<html>gateway</html>", content_type="text/html")

        with self.assertRaisesMessage(ProviderError, "not JSON"):
            fetch_incentives(18)

    @responses.activate
    def test_graphql_errors_raise(self):
        responses.post(API_URL, json={"errors": [{"message": "Cannot query field"}], "data": None})

        with self.assertRaisesMessage(ProviderError, "reported an error"):
            fetch_incentives(18)

    @responses.activate
    def test_oversized_body_is_rejected(self):
        responses.post(API_URL, json=payload(*range(40), points_per_uid=40))

        with self.assertRaisesMessage(ProviderError, "larger than this app accepts"):
            fetch_incentives(18)

    @responses.activate
    def test_empty_subnet_list_is_not_an_error(self):
        responses.post(API_URL, json={"data": {"subnets": []}})

        self.assertEqual(fetch_incentives(18), [])


class ChartTests(SimpleTestCase):
    def test_summary_ranks_uids_by_latest_value(self):
        points = extract_incentives(payload(1, 9, 4))
        ranked = summarise(points)["ranked"]

        self.assertEqual([row["uid"] for row in ranked], [9, 4, 1])
        self.assertEqual(ranked[0]["samples"], 3)

    def test_render_returns_png_and_caps_series(self):
        points = extract_incentives(payload(*range(MAX_PLOTTED_UIDS + 8)))

        png = render_chart_png(points, 18)

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_concurrent_renders_do_not_share_state(self):
        points = extract_incentives(payload(1, 2))
        results = []

        def render():
            results.append(render_chart_png(points, 3))

        threads = [threading.Thread(target=render) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 4)
        self.assertTrue(all(png.startswith(b"\x89PNG") for png in results))


@override_settings(GRAPHQL_API_URL=API_URL, GRAPHQL_SUBNET_UID=18, GRAPHQL_CACHE_SECONDS=60)
class PlotViewTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @responses.activate
    def test_chart_renders_for_configured_subnet(self):
        responses.post(API_URL, json=payload(1, 2))

        response = self.client.get(reverse("plot_view"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plot.html")
        self.assertContains(response, "Subnet 18")
        self.assertContains(response, "data:image/png;base64,")
        self.assertIn("subnets(netUid: 18)", json.loads(responses.calls[0].request.body)["query"])

    @responses.activate
    def test_query_parameter_selects_subnet(self):
        responses.post(API_URL, json=payload(3))

        response = self.client.get(reverse("plot_view"), {"subnet": "42"})

        self.assertContains(response, "Subnet 42")
        self.assertIn("subnets(netUid: 42)", json.loads(responses.calls[0].request.body)["query"])

    @responses.activate
    def test_invalid_subnet_is_rejected_without_a_request(self):
        for value in ["abc", "-1", "70000", "", "1.5"]:
            with self.subTest(value=value):
                response = self.client.get(reverse("plot_view"), {"subnet": value})
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, 'role="alert"', status_code=400)
        self.assertEqual(len(responses.calls), 0)

    @responses.activate
    def test_provider_failure_shows_error_state(self):
        responses.post(API_URL, status=500)

        response = self.client.get(reverse("plot_view"))

        self.assertEqual(response.status_code, 502)
        self.assertContains(response, "Unable to fetch incentives data", status_code=502)

    @responses.activate
    def test_empty_response_shows_empty_state(self):
        responses.post(API_URL, json={"data": {"subnets": []}})

        response = self.client.get(reverse("plot_view"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No incentive points for subnet 18")
        self.assertNotContains(response, "data:image/png")

    @responses.activate
    def test_successful_chart_is_cached(self):
        responses.post(API_URL, json=payload(1))

        self.client.get(reverse("plot_view"))
        second = self.client.get(reverse("plot_view"))

        self.assertEqual(len(responses.calls), 1)
        self.assertTrue(second.context["from_cache"])

    @responses.activate
    def test_failures_are_not_cached(self):
        responses.post(API_URL, status=503)
        responses.post(API_URL, json=payload(1))

        self.assertEqual(self.client.get(reverse("plot_view")).status_code, 502)
        self.assertEqual(self.client.get(reverse("plot_view")).status_code, 200)
        self.assertEqual(len(responses.calls), 2)


class HomeViewTests(SimpleTestCase):
    @responses.activate
    def test_home_renders_form_without_fetching(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        self.assertContains(response, 'name="subnet"')
        self.assertEqual(len(responses.calls), 0)


class SettingsParsingTests(SimpleTestCase):
    def test_bad_numeric_environment_values_fail_fast(self):
        from incentive_site.settings import _env_number

        for raw in ["abc", "-5", "nan"]:
            with self.subTest(raw=raw), patch.dict(os.environ, {"GRAPHQL_REQUEST_TIMEOUT": raw}):
                with self.assertRaises(ImproperlyConfigured):
                    _env_number("GRAPHQL_REQUEST_TIMEOUT", 10, float, 0.5)


SETTINGS_FILE = Path(__file__).resolve().parent.parent / "incentive_site" / "settings.py"


class SettingsEnvironmentTests(SimpleTestCase):
    def load(self, **env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "GRAPHQL_"))}
        with patch.dict(os.environ, {**clean, **env}, clear=True):
            return runpy.run_path(str(SETTINGS_FILE))

    def test_missing_secret_key_outside_debug_fails(self):
        with self.assertRaises(ImproperlyConfigured):
            self.load()

    def test_debug_generates_throwaway_key(self):
        loaded = self.load(DJANGO_DEBUG="1")
        self.assertTrue(loaded["DEBUG"])
        self.assertGreaterEqual(len(loaded["SECRET_KEY"]), 50)

    def test_wildcard_hosts_need_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            self.load(DJANGO_SECRET_KEY="x" * 50, DJANGO_ALLOWED_HOSTS="*")

    def test_production_mode_secures_cookies_and_parses_hosts(self):
        loaded = self.load(DJANGO_SECRET_KEY="x" * 50, DJANGO_ALLOWED_HOSTS=" example.org, ,www.example.org ")
        self.assertFalse(loaded["DEBUG"])
        self.assertEqual(loaded["ALLOWED_HOSTS"], ["example.org", "www.example.org"])
        self.assertTrue(loaded["SESSION_COOKIE_SECURE"])
        self.assertTrue(loaded["CSRF_COOKIE_SECURE"])
        self.assertNotIn("SECURE_PROXY_SSL_HEADER", loaded)
