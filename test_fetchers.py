"""离线测试 pet/fetchers.py。只打假 HTTP，不读本机配置或密钥。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent / "pet"))
import fetchers


class _Resp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.content = b"{}"
        self._payload = payload

    def json(self):
        return self._payload


class ParseChatgptTests(unittest.TestCase):
    def test_used_percent_kept_when_message_cap_over_100(self):
        snap = fetchers._parse_chatgpt(
            {"usage": {"used_percent": 25, "limit": 500}}
        )
        self.assertIsNotNone(snap)
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["unit"], "%")
        self.assertEqual(snap["amount"], 75)
        self.assertEqual(snap["remainingPct"], 75)

    def test_hunt_keeps_used_percent_zero(self):
        snap = fetchers._parse_chatgpt({"usage": {"used_percent": 0}})
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 100)
        self.assertEqual(snap["remainingPct"], 100)

    def test_hunt_keeps_remaining_zero(self):
        snap = fetchers._parse_chatgpt({"usage": {"remaining": 0, "limit": 500}})
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["remainingPct"], 0)

    def test_valid_primary_zero_uses_secondary_hint(self):
        snap = fetchers._parse_chatgpt({
            "rate_limit": {
                "primary_window": {"used_percent": 0},
                "secondary_window": {"used_percent": 20},
            }
        })
        self.assertEqual(snap["amount"], 100)
        self.assertIn("80", snap["hint"])

    def test_bad_primary_uses_percent_left(self):
        snap = fetchers._parse_chatgpt({
            "rate_limit": {"primary_window": {"used_percent": "bad", "percent_left": 40}}
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 40)
        self.assertEqual(snap["hint"], "额度窗口")

    def test_null_primary_uses_usage_fallback(self):
        snap = fetchers._parse_chatgpt({
            "rate_limit": {"primary_window": {"used_percent": None}},
            "usage": {"used_percent": 25, "limit": 500},
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 75)

    def test_nan_primary_uses_usage_fallback(self):
        snap = fetchers._parse_chatgpt({
            "rate_limit": {"primary_window": {"used_percent": float("nan")}},
            "usage": {"used_percent": 40},
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 60)

    def test_inf_primary_uses_secondary_via_fallback(self):
        snap = fetchers._parse_chatgpt({
            "rate_limit": {
                "primary_window": {"used_percent": float("inf")},
                "secondary_window": {"used_percent": 10},
            }
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 90)
        self.assertEqual(snap["hint"], "剩余额度")

    def test_bad_secondary_keeps_valid_primary(self):
        snap = fetchers._parse_chatgpt({
            "rate_limit": {
                "primary_window": {"used_percent": 30},
                "secondary_window": {"used_percent": "bad"},
            }
        })
        self.assertEqual(snap["amount"], 70)
        self.assertEqual(snap["hint"], "5 小时窗口")


class HttpStatusTests(unittest.TestCase):
    def test_api_money_500_is_error_even_if_body_has_balance(self):
        payload = {"data": {"totalBalance": 12.5}}
        with patch.object(fetchers.requests, "get", return_value=_Resp(500, payload)):
            snap = fetchers.fetch_api_money(
                "https://example.test/balance",
                "sk-test",
                ["data.totalBalance"],
                "CNY",
                "硅基流动",
            )
        self.assertFalse(snap["ok"])
        self.assertNotIn("amount", snap)

    def test_api_money_200_still_parses(self):
        payload = {"data": {"totalBalance": 12.5}}
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, payload)):
            snap = fetchers.fetch_api_money(
                "https://example.test/balance",
                "sk-test",
                ["data.totalBalance"],
                "CNY",
                "硅基流动",
            )
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 12.5)
        self.assertEqual(snap["unit"], "CNY")

    def test_custom_401_is_error_even_if_body_has_number(self):
        payload = {"balance": 88}
        item = {
            "name": "自定义",
            "url": "https://example.test/bal",
            "api_key": "",
            "json_path": "balance",
            "unit": "CNY",
        }
        with patch.object(fetchers.requests, "get", return_value=_Resp(401, payload)):
            snap = fetchers.fetch_custom(item)
        self.assertFalse(snap["ok"])
        self.assertNotIn("amount", snap)

    def test_api_money_401_and_403_are_invalid_key(self):
        payload = {"data": {"totalBalance": 9}}
        for status in (401, 403):
            with patch.object(fetchers.requests, "get", return_value=_Resp(status, payload)):
                snap = fetchers.fetch_api_money(
                    "https://example.test/balance",
                    "sk-test",
                    ["data.totalBalance"],
                    "CNY",
                    "硅基流动",
                )
            self.assertFalse(snap["ok"])
            self.assertIn("Key", snap["error"])

    def test_api_money_empty_key_does_not_request(self):
        with patch.object(fetchers.requests, "get") as get:
            snap = fetchers.fetch_api_money(
                "https://example.test/balance", "", ["data.totalBalance"], "CNY", "硅基流动"
            )
        get.assert_not_called()
        self.assertFalse(snap["ok"])
        self.assertIn("Key", snap["error"])

    def test_custom_without_key_200(self):
        item = {
            "name": "自定义",
            "url": "https://example.test/bal",
            "api_key": "",
            "json_path": "balance",
            "unit": "CNY",
        }
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"balance": 3})):
            snap = fetchers.fetch_custom(item)
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 3)

    def test_custom_with_key_403(self):
        item = {
            "name": "自定义",
            "url": "https://example.test/bal",
            "api_key": "sk-test",
            "json_path": "balance",
            "unit": "CNY",
        }
        with patch.object(fetchers.requests, "get", return_value=_Resp(403, {"balance": 88})):
            snap = fetchers.fetch_custom(item)
        self.assertFalse(snap["ok"])
        self.assertIn("Key", snap["error"])

    def test_custom_with_key_200(self):
        item = {
            "name": "自定义",
            "url": "https://example.test/bal",
            "api_key": "sk-test",
            "json_path": "balance",
            "unit": "CNY",
        }
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"balance": 6})):
            snap = fetchers.fetch_custom(item)
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 6)


class NumTests(unittest.TestCase):
    def test_huge_int_is_none(self):
        self.assertIsNone(fetchers._num(10**1000))


class ParseCursorTests(unittest.TestCase):
    def test_total_percent_zero_beats_alias(self):
        snap = fetchers._parse_cursor({
            "planUsage": {"totalPercentUsed": 0, "total_percent_used": 40}
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 100)
        self.assertEqual(snap["remainingPct"], 100)
        self.assertEqual(snap["hint"], "已用 0%")

    def test_auto_percent_zero_shows_full(self):
        snap = fetchers._parse_cursor({
            "planUsage": {"autoPercentUsed": 0, "auto_percent_used": 30}
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 100)
        self.assertEqual(snap["remainingPct"], 100)
        self.assertEqual(snap["unit"], "%")
        self.assertEqual(snap["hint"], "Auto 100%")

    def test_included_spend_zero_computes_remaining(self):
        snap = fetchers._parse_cursor({
            "individualUsage": {"plan": {"limit": 200}},
            "planUsage": {"includedSpend": 0, "included_spend": 80},
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 2)
        self.assertEqual(snap["unit"], "USD")
        self.assertEqual(snap["remainingPct"], 100)

    def test_remaining_zero_not_replaced_by_fallback(self):
        snap = fetchers._parse_cursor({
            "individualUsage": {
                "plan": {"remaining": 0, "limit": 200},
                "overall": {"remaining": 80},
            },
            "planUsage": {"remaining": 50},
        })
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["remainingPct"], 0)
        self.assertEqual(snap["unit"], "USD")

    def test_bad_nodes_do_not_crash_and_keep_valid_sibling(self):
        snap = fetchers._parse_cursor({
            "individualUsage": [1],
            "planUsage": {"totalPercentUsed": 10},
        })
        self.assertEqual(snap["amount"], 90)
        self.assertEqual(snap["hint"], "已用 10%")

        snap = fetchers._parse_cursor({
            "individualUsage": {"plan": None, "overall": {"remaining": 4, "limit": 10}},
            "planUsage": "no",
        })
        self.assertEqual(snap["amount"], 4)
        self.assertEqual(snap["unit"], "次")
        self.assertEqual(snap["remainingPct"], 40)

        snap = fetchers._parse_cursor({
            "individualUsage": {"plan": [], "overall": "x"},
            "planUsage": [1],
            "plan_usage": {"autoPercentUsed": 0},
        })
        self.assertEqual(snap["amount"], 100)
        self.assertEqual(snap["hint"], "Auto 100%")

    def test_no_valid_numbers_returns_none(self):
        for data in (
            {"individualUsage": [1]},
            {"individualUsage": None, "planUsage": None},
            {"individualUsage": "usage", "planUsage": "usage"},
            {"individualUsage": {"plan": [], "overall": "x"}, "planUsage": 1},
        ):
            self.assertIsNone(fetchers._parse_cursor(data))


def _real_response(status: int, body: bytes) -> requests.Response:
    res = requests.Response()
    res.status_code = status
    res._content = body
    res.encoding = "utf-8"
    res.url = "https://example.test/bal"
    return res


_OR_BODY = {
    "data": {
        "total_credits": 100,
        "total_usage": 20,
        "limit_remaining": 88,
        "limit": 100,
    }
}


class HttpSuccessTests(unittest.TestCase):
    def _custom(self, status: int, body: bytes = b'{"balance":88}'):
        item = {
            "name": "自定义",
            "url": "https://example.test/bal",
            "api_key": "",
            "json_path": "balance",
            "unit": "CNY",
        }
        with patch.object(fetchers.requests, "get", return_value=_real_response(status, body)):
            return fetchers.fetch_custom(item)

    def test_custom_nokey_real_response_only_2xx(self):
        self.assertTrue(_real_response(302, b'{"balance":88}').ok)
        for status in (200, 201):
            snap = self._custom(status, b'{"balance":0}' if status == 201 else b'{"balance":88}')
            self.assertTrue(snap["ok"], status)
            self.assertEqual(snap["amount"], 0 if status == 201 else 88)
            self.assertEqual(snap["unit"], "CNY")
        for status in (302, 429, 500, 401, 403):
            snap = self._custom(status)
            self.assertFalse(snap["ok"], status)
            self.assertIn(str(status), snap["error"])
            self.assertIn("HTTP", snap["error"])
            self.assertNotIn("结构", snap["error"])

    def test_openrouter_credits_non_2xx_not_success(self):
        for status in (302, 429, 500):
            calls = []

            def side(url, key, status=status):
                calls.append(url)
                return status, _OR_BODY

            with patch.object(fetchers, "_bearer_json", side_effect=side):
                snap = fetchers.fetch_openrouter("sk-or-test")
            self.assertFalse(snap["ok"], status)
            self.assertIn(str(status), snap["error"])
            self.assertNotIn("结构", snap["error"])
            self.assertEqual(len(calls), 2)

    def test_openrouter_key_fallback_non_2xx_not_success(self):
        calls = []

        def side(url, key):
            calls.append(url)
            if url.endswith("/credits"):
                return 500, {"data": {}}
            return 302, _OR_BODY

        with patch.object(fetchers, "_bearer_json", side_effect=side):
            snap = fetchers.fetch_openrouter("sk-or-test")
        self.assertFalse(snap["ok"])
        self.assertIn("302", snap["error"])
        self.assertIn("HTTP", snap["error"])
        self.assertNotIn("结构", snap["error"])
        self.assertEqual([u.rsplit("/", 1)[-1] for u in calls], ["credits", "key"])

    def test_openrouter_credits_2xx_skips_key_and_keeps_zero(self):
        for status, credits, usage, amount in ((200, 100, 20, 80), (201, 0, 0, 0)):
            calls = []

            def side(url, key, status=status, credits=credits, usage=usage):
                calls.append(url)
                return status, {"data": {"total_credits": credits, "total_usage": usage, "limit_remaining": 1, "limit": 2}}

            with patch.object(fetchers, "_bearer_json", side_effect=side):
                snap = fetchers.fetch_openrouter("sk-or-test")
            self.assertTrue(snap["ok"], status)
            self.assertEqual(snap["amount"], amount)
            self.assertEqual(snap["unit"], "USD")
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0].endswith("/credits"))

    def test_openrouter_credits_fail_then_key_200(self):
        calls = []

        def side(url, key):
            calls.append(url)
            if url.endswith("/credits"):
                return 500, _OR_BODY
            return 200, {"data": {"limit_remaining": 0, "limit": 100}}

        with patch.object(fetchers, "_bearer_json", side_effect=side):
            snap = fetchers.fetch_openrouter("sk-or-test")
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["hint"], "Key 剩余")
        self.assertEqual([u.rsplit("/", 1)[-1] for u in calls], ["credits", "key"])

    def test_openrouter_401_403_invalid_key(self):
        for status in (401, 403):
            def side(url, key, status=status):
                return status, _OR_BODY

            with patch.object(fetchers, "_bearer_json", side_effect=side):
                snap = fetchers.fetch_openrouter("sk-or-test")
            self.assertFalse(snap["ok"])
            self.assertIn("Key", snap["error"])


class _HtmlResponse(requests.Response):
    def __init__(self, status: int, body: bytes):
        super().__init__()
        self.status_code = status
        self._content = body
        self.encoding = "utf-8"
        self.url = "https://example.test/bal"
        self.json_calls = 0

    def json(self, **kwargs):
        self.json_calls += 1
        return super().json(**kwargs)


def _ds_response(status: int, body: bytes) -> requests.Response:
    res = requests.Response()
    res.status_code = status
    res._content = body
    res.encoding = "utf-8"
    res.url = "https://api.deepseek.com/user/balance"
    return res


_DS_OK = b'{"balance_infos":[{"total_balance":"88","currency":"CNY"}]}'
_DS_ZERO = b'{"balance_infos":[{"total_balance":"0","currency":"CNY"}]}'


class FetchEdgeTests(unittest.TestCase):
    def test_custom_error_html_skips_json(self):
        item = {
            "name": "自定义",
            "url": "https://example.test/bal",
            "api_key": "",
            "json_path": "balance",
            "unit": "CNY",
        }
        for status in (302, 429, 500):
            res = _HtmlResponse(status, b"<html>fake upstream error</html>")
            with patch.object(fetchers.requests, "get", return_value=res):
                snap = fetchers.fetch_custom(item)
            self.assertEqual(res.json_calls, 0, status)
            self.assertFalse(snap["ok"], status)
            self.assertIn("HTTP", snap["error"])
            self.assertIn(str(status), snap["error"])
            self.assertNotIn("请求失败", snap["error"])

    def test_deepseek_302_complete_json_is_not_success(self):
        res = _ds_response(302, _DS_OK)
        self.assertTrue(res.ok)
        with patch.object(fetchers.requests, "get", return_value=res) as get:
            snap = fetchers.fetch_deepseek("sk-test")
        self.assertFalse(snap["ok"])
        self.assertIn("HTTP", snap["error"])
        self.assertIn("302", snap["error"])
        self.assertEqual(get.call_count, 1)

    def test_deepseek_2xx_and_zero(self):
        for status, body, amount in ((200, _DS_OK, 88), (201, _DS_ZERO, 0), (200, _DS_ZERO, 0)):
            res = _ds_response(status, body)
            with patch.object(fetchers.requests, "get", return_value=res) as get:
                snap = fetchers.fetch_deepseek("sk-test")
            self.assertTrue(snap["ok"], status)
            self.assertEqual(snap["amount"], amount)
            self.assertEqual(snap["unit"], "CNY")
            self.assertEqual(get.call_count, 1)

    def test_deepseek_500_then_200_retries_once(self):
        side = [_ds_response(500, b"<html>fake upstream error</html>"), _ds_response(200, _DS_OK)]
        with patch.object(fetchers.requests, "get", side_effect=side) as get:
            snap = fetchers.fetch_deepseek("sk-test")
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 88)
        self.assertEqual(get.call_count, 2)

    def test_deepseek_500_then_500_stops(self):
        side = [
            _ds_response(500, b"<html>fake upstream error</html>"),
            _ds_response(500, b"<html>fake upstream error</html>"),
        ]
        with patch.object(fetchers.requests, "get", side_effect=side) as get:
            snap = fetchers.fetch_deepseek("sk-test")
        self.assertFalse(snap["ok"])
        self.assertIn("HTTP", snap["error"])
        self.assertIn("500", snap["error"])
        self.assertEqual(get.call_count, 2)

    def test_deepseek_network_then_200(self):
        calls = {"n": 0}

        def side(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("down")
            return _ds_response(200, _DS_OK)

        with patch.object(fetchers.requests, "get", side_effect=side):
            snap = fetchers.fetch_deepseek("sk-test")
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 88)
        self.assertEqual(calls["n"], 2)

    def test_deepseek_401_does_not_retry(self):
        res = _ds_response(401, _DS_OK)
        with patch.object(fetchers.requests, "get", return_value=res) as get:
            snap = fetchers.fetch_deepseek("sk-test")
        self.assertFalse(snap["ok"])
        self.assertIn("Key", snap["error"])
        self.assertEqual(get.call_count, 1)


def _mock_get(payload):
    return patch.object(fetchers.requests, "get", return_value=_Resp(200, payload))


class DeepSeekShapeTests(unittest.TestCase):
    def _fetch(self, payload):
        with _mock_get(payload) as get:
            snap = fetchers.fetch_deepseek("sk-fake")
        self.assertEqual(get.call_args.args[0], "https://api.deepseek.com/user/balance")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer sk-fake")
        return snap

    def test_balance_infos_not_list(self):
        for infos in ({"total_balance": 9}, "bad", 1, True):
            snap = self._fetch({"balance_infos": infos})
            self.assertFalse(snap["ok"])
            self.assertIn("结构变了", snap["error"])
            self.assertNotIn("amount", snap)

    def test_balance_infos_empty(self):
        snap = self._fetch({"balance_infos": []})
        self.assertFalse(snap["ok"])
        self.assertIn("结构变了", snap["error"])

    def test_mixed_bad_then_good(self):
        snap = self._fetch({
            "balance_infos": [
                1,
                "bad",
                True,
                {"currency": "CNY"},
                {"total_balance": "nope", "currency": "CNY"},
                {"total_balance": 12.5, "currency": "USD"},
            ]
        })
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 12.5)
        self.assertEqual(snap["unit"], "USD")

    def test_mixed_bad_then_zero(self):
        snap = self._fetch({"balance_infos": [1, {"total_balance": 0, "currency": "CNY"}]})
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["unit"], "CNY")

    def test_dict_missing_total(self):
        snap = self._fetch({"balance_infos": [{"currency": "CNY"}]})
        self.assertFalse(snap["ok"])
        self.assertIn("结构变了", snap["error"])

    def test_total_not_number(self):
        snap = self._fetch({"balance_infos": [{"total_balance": "bad", "currency": "CNY"}]})
        self.assertFalse(snap["ok"])
        self.assertIn("余额异常", snap["error"])
        self.assertNotIn("amount", snap)


class OpenAIAdminShapeTests(unittest.TestCase):
    def _costs(self, payload):
        with _mock_get(payload) as get:
            snap = fetchers._openai_admin_costs("sk-admin-fake")
        self.assertIn("https://api.openai.com/v1/organization/costs", get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer sk-admin-fake")
        return snap

    def test_data_not_list(self):
        for data in (1, {}, "no", None, True):
            snap = self._costs({"data": data})
            self.assertFalse(snap["ok"])
            self.assertIn("返回异常", snap["error"])
            self.assertNotIn("amount", snap)

    def test_bucket_not_dict(self):
        snap = self._costs({"data": [1]})
        self.assertFalse(snap["ok"])
        self.assertIn("返回异常", snap["error"])

    def test_results_not_list(self):
        for results in (1, {}, "no"):
            snap = self._costs({"data": [{"results": results}]})
            self.assertFalse(snap["ok"], results)
            self.assertIn("返回异常", snap["error"])

    def test_amount_not_dict(self):
        snap = self._costs({"data": [{"results": [{"amount": 1}]}]})
        self.assertFalse(snap["ok"])
        self.assertIn("返回异常", snap["error"])

    def test_bad_and_good_amounts_sum(self):
        snap = self._costs({
            "data": [
                1,
                {"results": 1},
                {"results": [1, {"amount": 1}, {"amount": {"currency": "eur", "value": 9}}]},
                {"results": [
                    {"amount": {"currency": "usd", "value": 2.5}},
                    {"amount": {"value": 1.5}},
                    {"amount": {"currency": "usd", "value": 0}},
                ]},
            ]
        })
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 4.0)
        self.assertEqual(snap["unit"], "USD")

    def test_empty_list_is_zero(self):
        for payload in ({"data": []}, {"data": [{"results": []}]}):
            snap = self._costs(payload)
            self.assertTrue(snap["ok"])
            self.assertEqual(snap["amount"], 0)

    def test_zero_amount_kept(self):
        snap = self._costs({"data": [{"results": [{"amount": {"currency": "usd", "value": 0}}]}]})
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)


class OpenAIFallbackTests(unittest.TestCase):
    def _get(self, side):
        return patch.object(fetchers.requests, "get", side_effect=side)

    def test_admin_bad_json_grants_zero(self):
        costs = _HtmlResponse(200, b"not-json")
        grants = _HtmlResponse(200, b'{"total_available":0}')

        def side(url, **kwargs):
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-admin-fake")
            if "organization/costs" in url:
                return costs
            if "credit_grants" in url:
                return grants
            raise AssertionError(url)

        with self._get(side) as get:
            snap = fetchers.fetch_openai("sk-admin-fake")
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["unit"], "USD")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(costs.json_calls, 1)

    def test_both_bad_json_or_shape_do_not_raise(self):
        def side(url, **kwargs):
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-admin-fake")
            if "organization/costs" in url:
                return _HtmlResponse(200, b"<html>")
            if "credit_grants" in url:
                return _HtmlResponse(200, b"[]")
            raise AssertionError(url)

        with self._get(side):
            snap = fetchers.fetch_openai("sk-admin-fake")
        self.assertFalse(snap["ok"])
        self.assertIn("返回异常", snap["error"])
        self.assertNotIn("amount", snap)

    def test_admin_success_skips_grants(self):
        body = b'{"data":[{"results":[{"amount":{"currency":"usd","value":3}}]}]}'

        def side(url, **kwargs):
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-admin-fake")
            self.assertNotIn("credit_grants", url)
            self.assertIn("organization/costs", url)
            return _HtmlResponse(200, body)

        with self._get(side) as get:
            snap = fetchers.fetch_openai("sk-admin-fake")
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 3)
        self.assertEqual(get.call_count, 1)

    def test_non_200_html_does_not_parse_json(self):
        admin = _HtmlResponse(500, b"<html>nope</html>")
        grants = _HtmlResponse(403, b"<html>nope</html>")

        def side(url, **kwargs):
            if "organization/costs" in url:
                return admin
            if "credit_grants" in url:
                return grants
            raise AssertionError(url)

        with self._get(side):
            snap = fetchers.fetch_openai("sk-admin-fake")
        self.assertEqual(admin.json_calls, 0)
        self.assertEqual(grants.json_calls, 0)
        self.assertFalse(snap["ok"])
        self.assertIn("500", snap["error"])
        self.assertIn("403", snap["error"])

    def test_admin_blank_nodes_are_not_zero(self):
        bodies = (
            b'{"data":[{}]}',
            b'{"data":[{"results":null}]}',
            b'{"data":[{"results":[{}]}]}',
            b'{"data":[{"results":[{"amount":null}]}]}',
            b'{"data":[{"results":[{"amount":{}}]}]}',
            b'{"data":[{"results":[{"amount":{"currency":"usd","value":null}}]}]}',
        )
        for body in bodies:
            res = _HtmlResponse(200, body)
            with patch.object(fetchers.requests, "get", return_value=res):
                snap = fetchers._openai_admin_costs("sk-admin-fake")
            self.assertFalse(snap["ok"], body)
            self.assertIn("返回异常", snap["error"])
            self.assertNotIn("amount", snap)

    def test_admin_bad_json_and_grants_list(self):
        with patch.object(fetchers.requests, "get", return_value=_HtmlResponse(200, b"not-json")):
            admin = fetchers._openai_admin_costs("sk-admin-fake")
        with patch.object(fetchers.requests, "get", return_value=_HtmlResponse(200, b"[]")):
            grants = fetchers._openai_credit_grants("sk-admin-fake")
        self.assertFalse(admin["ok"])
        self.assertFalse(grants["ok"])
        self.assertIn("返回异常", admin["error"])
        self.assertIn("返回异常", grants["error"])

    def test_real_empty_and_zero_still_succeed(self):
        cases = (
            b'{"data":[]}',
            b'{"data":[{"results":[]}]}',
            b'{"data":[{"results":[{"amount":{"currency":"usd","value":0}}]}]}',
            b'{"data":[{},{"results":[{"amount":{"value":2}},{"amount":null}]}]}',
        )
        expect = (0, 0, 0, 2)
        for body, amount in zip(cases, expect):
            res = _HtmlResponse(200, body)
            with patch.object(fetchers.requests, "get", return_value=res):
                snap = fetchers._openai_admin_costs("sk-admin-fake")
            self.assertTrue(snap["ok"], body)
            self.assertEqual(snap["amount"], amount)


_CURSOR_PLAN = b'{"planUsage":{"remaining":80,"limit":100}}'
_CURSOR_ZERO = b'{"planUsage":{"remaining":0,"limit":100}}'
_CURSOR_INF = b'{"isUnlimited":true}'
_GPT_AUTH = b'{"accessToken":"fake-chatgpt-token","account":{"id":"fake-acct"}}'
_GPT_USED = b'{"rate_limit":{"primary_window":{"used_percent":20}}}'
_GPT_ZERO = b'{"message_cap":0}'
_GEMINI_USED = b"<html>used 20%</html>"
_GEMINI_ZERO = b"<html>used 100%</html>"


class HttpGateTests(unittest.TestCase):
    def setUp(self):
        self.db = patch.object(fetchers.sqlite3, "connect", side_effect=AssertionError("db"))
        self.db_mock = self.db.start()
        self.addCleanup(self.db.stop)
        self.real_get = patch.object(fetchers.requests, "get", side_effect=AssertionError("real get"))
        self.real_get_mock = self.real_get.start()
        self.addCleanup(self.real_get.stop)
        self.real_post = patch.object(fetchers.requests, "post", side_effect=AssertionError("real post"))
        self.real_post_mock = self.real_post.start()
        self.addCleanup(self.real_post.stop)
        self.domains = []

        def jar(domains):
            self.domains.append(list(domains))
            box = requests.cookies.RequestsCookieJar()
            box.set("fake_session", "fake-cookie", domain=domains[0], path="/")
            return box

        self.jar = patch.object(fetchers, "_cookie_jar", side_effect=jar)
        self.jar.start()
        self.addCleanup(self.jar.stop)
        self.token_patch = patch.object(fetchers, "_cursor_token", return_value="fake-cursor-token")
        self.token = self.token_patch.start()
        self.addCleanup(self.token_patch.stop)

    def assert_isolated(self):
        self.db_mock.assert_not_called()
        self.real_get_mock.assert_not_called()

    def test_cursor_error_body_is_not_success(self):
        for status in (302, 429, 500):
            summary = _HtmlResponse(status, _CURSOR_PLAN)
            period = _HtmlResponse(status, _CURSOR_PLAN)
            token = _HtmlResponse(status, _CURSOR_PLAN)
            posts = []

            def _get(url, jar=None, headers=None, method="GET", body=None, summary=summary, period=period):
                return period if method == "POST" else summary

            def post(url, **kwargs):
                posts.append(url)
                self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-cursor-token")
                return token

            with patch.object(fetchers, "_get", side_effect=_get), patch.object(fetchers.requests, "post", side_effect=post):
                snap = fetchers.fetch_cursor()
            self.assertFalse(snap["ok"], status)
            self.assertIn(str(status), snap["error"])
            self.assertNotIn("结构变了", snap["error"])
            self.assertNotIn("amount", snap)
            self.assertEqual(summary.json_calls, 0)
            self.assertEqual(period.json_calls, 0)
            self.assertEqual(token.json_calls, 0)
            self.assertTrue(posts)
        self.assert_isolated()

    def test_cursor_summary_stops_and_keeps_zero(self):
        for status, body, amount, unit in (
            (200, _CURSOR_PLAN, 0.8, "USD"),
            (201, _CURSOR_PLAN, 0.8, "USD"),
            (200, _CURSOR_ZERO, 0, "USD"),
            (200, _CURSOR_INF, float("inf"), ""),
        ):
            calls = []

            def _get(url, jar=None, headers=None, method="GET", body=None, status=status, payload=body):
                calls.append((method, url))
                if "usage-summary" not in url:
                    raise AssertionError(url)
                return _HtmlResponse(status, payload)

            with patch.object(fetchers, "_get", side_effect=_get):
                snap = fetchers.fetch_cursor()
            self.assertTrue(snap["ok"], body)
            self.assertEqual(snap["amount"], amount)
            self.assertEqual(snap["unit"], unit)
            self.assertEqual(len(calls), 1)
            self.token.assert_not_called()
        self.assert_isolated()
        self.real_post_mock.assert_not_called()

    def test_cursor_fallback_order(self):
        summary = _HtmlResponse(401, _CURSOR_PLAN)
        calls = []
        token = _HtmlResponse(401, _CURSOR_PLAN)

        def _get(url, jar=None, headers=None, method="GET", body=None):
            calls.append(url)
            return summary

        def post(url, **kwargs):
            calls.append(url)
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-cursor-token")
            return token

        with patch.object(fetchers, "_get", side_effect=_get), patch.object(fetchers.requests, "post", side_effect=post):
            expired = fetchers.fetch_cursor()
        self.assertIn("登录已过期", expired["error"])
        self.assertEqual(summary.json_calls, 0)
        self.assertEqual(token.json_calls, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("usage-summary", calls[0])
        self.assertIn("GetCurrentPeriodUsage", calls[1])

        summary = _HtmlResponse(500, b"<html>planUsage</html>")
        period = _HtmlResponse(201, _CURSOR_PLAN)
        calls.clear()

        def _get2(url, jar=None, headers=None, method="GET", body=None):
            calls.append((method, url))
            return period if method == "POST" else summary

        with patch.object(fetchers, "_get", side_effect=_get2):
            snap = fetchers.fetch_cursor()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0.8)
        self.assertEqual(summary.json_calls, 0)
        self.assertEqual(period.json_calls, 1)
        self.assertEqual([item[0] for item in calls], ["GET", "POST"])
        self.real_post_mock.assert_not_called()
        self.assert_isolated()

    def test_cursor_token_after_cookie_errors(self):
        summary = _HtmlResponse(500, _CURSOR_PLAN)
        period = _HtmlResponse(429, _CURSOR_PLAN)
        token = _HtmlResponse(201, _CURSOR_ZERO)
        calls = []

        def _get(url, jar=None, headers=None, method="GET", body=None):
            calls.append(method)
            return period if method == "POST" else summary

        def post(url, **kwargs):
            calls.append("token")
            return token

        with patch.object(fetchers, "_get", side_effect=_get), patch.object(fetchers.requests, "post", side_effect=post):
            snap = fetchers.fetch_cursor()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["unit"], "USD")
        self.assertEqual(calls, ["GET", "POST", "token"])
        self.assertEqual(summary.json_calls, 0)
        self.assertEqual(period.json_calls, 0)
        self.assertEqual(token.json_calls, 1)

        empty = _HtmlResponse(200, b"{}")
        token_empty = _HtmlResponse(200, b"{}")

        def _get_empty(url, jar=None, headers=None, method="GET", body=None):
            return empty

        def post_empty(url, **kwargs):
            return token_empty

        with patch.object(fetchers, "_get", side_effect=_get_empty), patch.object(fetchers.requests, "post", side_effect=post_empty):
            bad = fetchers.fetch_cursor()
        self.assertFalse(bad["ok"])
        self.assertIn("结构变了", bad["error"])

    def test_chatgpt_auth_non_2xx_stops(self):
        for status in (302, 429, 500, 401, 403):
            auth = _HtmlResponse(status, _GPT_AUTH)

            def _get(url, jar=None, headers=None, method="GET", body=None, auth=auth):
                if "auth/session" not in url:
                    raise AssertionError(url)
                return auth

            with patch.object(fetchers, "_get", side_effect=_get):
                snap = fetchers.fetch_chatgpt()
            self.assertFalse(snap["ok"], status)
            self.assertEqual(auth.json_calls, 0)
            if status in (401, 403):
                self.assertIn("登录", snap["error"])
            else:
                self.assertIn(str(status), snap["error"])
                self.assertIn("HTTP", snap["error"])
        self.assert_isolated()
        self.real_post_mock.assert_not_called()

    def test_chatgpt_wham_and_fallback(self):
        auth = _HtmlResponse(200, _GPT_AUTH)
        wham = _HtmlResponse(200, _GPT_USED)
        calls = []

        def _get(url, jar=None, headers=None, method="GET", body=None):
            calls.append(url)
            if "wham" in url:
                self.assertEqual(headers["Authorization"], "Bearer fake-chatgpt-token")
                return wham
            return auth

        with patch.object(fetchers, "_get", side_effect=_get):
            snap = fetchers.fetch_chatgpt()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 80)
        self.assertEqual(snap["unit"], "%")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("conversation_limit" not in url for url in calls))

        auth = _HtmlResponse(201, _GPT_AUTH)
        wham = _HtmlResponse(500, _GPT_USED)
        limit = _HtmlResponse(201, _GPT_ZERO)
        calls.clear()

        def _get_fb(url, jar=None, headers=None, method="GET", body=None):
            calls.append(url)
            if "wham" in url:
                return wham
            if "conversation_limit" in url:
                return limit
            return auth

        with patch.object(fetchers, "_get", side_effect=_get_fb):
            snap = fetchers.fetch_chatgpt()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["unit"], "条")
        self.assertEqual(wham.json_calls, 0)
        self.assertEqual(limit.json_calls, 1)
        self.assertEqual(len(calls), 3)

        wham = _HtmlResponse(500, _GPT_USED)
        limit = _HtmlResponse(500, _GPT_USED)

        def _get_both(url, jar=None, headers=None, method="GET", body=None):
            if "wham" in url:
                return wham
            if "conversation_limit" in url:
                return limit
            return _HtmlResponse(200, _GPT_AUTH)

        with patch.object(fetchers, "_get", side_effect=_get_both):
            snap = fetchers.fetch_chatgpt()
        self.assertFalse(snap["ok"])
        self.assertIn("500", snap["error"])
        self.assertEqual(wham.json_calls, 0)
        self.assertEqual(limit.json_calls, 0)
        self.assert_isolated()

    def test_google_non_2xx_skips_html(self):
        seen = {"n": 0}
        real = fetchers._parse_gemini_html

        def spy(html):
            seen["n"] += 1
            return real(html)

        for status in (302, 429, 500, 401, 403):
            seen["n"] = 0
            res = _HtmlResponse(status, _GEMINI_USED)
            with patch.object(fetchers, "_get", return_value=res), patch.object(fetchers, "_parse_gemini_html", spy):
                snap = fetchers.fetch_google()
            self.assertFalse(snap["ok"], status)
            self.assertEqual(seen["n"], 0)
            self.assertEqual(res.json_calls, 0)
            if status in (401, 403):
                self.assertIn("登录", snap["error"])
            else:
                self.assertIn(str(status), snap["error"])
                self.assertIn("HTTP", snap["error"])

        for status, body, amount in ((200, _GEMINI_USED, 80), (201, _GEMINI_ZERO, 0)):
            res = _HtmlResponse(status, body)
            with patch.object(fetchers, "_get", return_value=res):
                snap = fetchers.fetch_google()
            self.assertTrue(snap["ok"], status)
            self.assertEqual(snap["amount"], amount)
            self.assertEqual(snap["unit"], "%")
        self.assert_isolated()
        self.assertIn("gemini.google.com", self.domains[-1])


class BoolNumTests(unittest.TestCase):
    def test_num_rejects_bool_keeps_zero_and_bad(self):
        self.assertIsNone(fetchers._num(True))
        self.assertIsNone(fetchers._num(False))
        self.assertEqual(fetchers._num(0), 0.0)
        self.assertEqual(fetchers._num(0.0), 0.0)
        self.assertEqual(fetchers._num("0"), 0.0)
        self.assertEqual(fetchers._num(3), 3.0)
        self.assertEqual(fetchers._num(1.5), 1.5)
        self.assertEqual(fetchers._num("12.5"), 12.5)
        self.assertIsNone(fetchers._num("bad"))
        self.assertIsNone(fetchers._num(float("nan")))
        self.assertIsNone(fetchers._num(float("inf")))
        self.assertIsNone(fetchers._num(float("-inf")))

    def test_cursor_bool_remaining_not_zero(self):
        self.assertIsNone(fetchers._parse_cursor({"planUsage": {"remaining": False, "limit": 100}}))
        self.assertIsNone(fetchers._parse_cursor({"planUsage": {"remaining": True, "limit": 100}}))
        snap = fetchers._parse_cursor({
            "individualUsage": {
                "plan": {"remaining": False, "limit": 100},
                "overall": {"remaining": 5},
            }
        })
        self.assertEqual(snap["amount"], 0.05)
        self.assertEqual(snap["unit"], "USD")
        unlimited = fetchers._parse_cursor({"isUnlimited": True, "planUsage": {"remaining": False, "limit": 100}})
        self.assertEqual(unlimited["amount"], float("inf"))
        self.assertEqual(unlimited["hint"], "不限量")

    def test_chatgpt_bool_percent_uses_fallback(self):
        self.assertIsNone(fetchers._parse_chatgpt({
            "rate_limit": {"primary_window": {"used_percent": False}}
        }))
        snap = fetchers._parse_chatgpt({
            "rate_limit": {"primary_window": {"used_percent": True, "percent_left": 0}}
        })
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["hint"], "额度窗口")

    def test_deepseek_bool_balance(self):
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {
            "balance_infos": [{"total_balance": True, "currency": "CNY"}]
        })) as get:
            bad = fetchers.fetch_deepseek("sk-fake")
        self.assertFalse(bad["ok"])
        self.assertNotIn("amount", bad)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer sk-fake")
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {
            "balance_infos": [
                {"total_balance": True, "currency": "CNY"},
                {"total_balance": False, "currency": "CNY"},
                {"total_balance": 0, "currency": "CNY"},
            ]
        })):
            snap = fetchers.fetch_deepseek("sk-fake")
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        self.assertEqual(snap["unit"], "CNY")

    def test_admin_and_grants_bool_amount(self):
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {
            "data": [{"results": [{"amount": {"currency": "usd", "value": True}}]}]
        })) as get:
            bad = fetchers._openai_admin_costs("sk-admin-fake")
        self.assertFalse(bad["ok"])
        self.assertNotIn("amount", bad)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer sk-admin-fake")
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {
            "data": [{"results": [
                {"amount": {"currency": "usd", "value": True}},
                {"amount": {"currency": "usd", "value": False}},
                {"amount": {"currency": "usd", "value": 0}},
            ]}]
        })):
            snap = fetchers._openai_admin_costs("sk-admin-fake")
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"total_available": True})):
            grant = fetchers._openai_credit_grants("sk-admin-fake")
        self.assertFalse(grant["ok"])
        self.assertNotIn("amount", grant)
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"total_available": False})):
            grant_false = fetchers._openai_credit_grants("sk-admin-fake")
        self.assertFalse(grant_false["ok"])
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"total_available": 0})):
            zero = fetchers._openai_credit_grants("sk-admin-fake")
        self.assertTrue(zero["ok"])
        self.assertEqual(zero["amount"], 0)

    def test_api_money_and_custom_bool_field(self):
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"data": {"balance": True, "backup": 0}})):
            bad = fetchers.fetch_api_money(
                "https://example.test/balance", "sk-fake", ["data.balance"], "CNY", "虚构"
            )
        self.assertFalse(bad["ok"])
        self.assertNotIn("amount", bad)
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"data": {"backup": 0}})):
            snap = fetchers.fetch_api_money(
                "https://example.test/balance",
                "sk-fake",
                ["data.missing", "data.backup"],
                "CNY",
                "虚构",
            )
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["amount"], 0)
        item = {
            "name": "自定义",
            "url": "https://example.test/bal",
            "api_key": "",
            "json_path": "balance",
            "unit": "CNY",
        }
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"balance": False})):
            custom_false = fetchers.fetch_custom(item)
        self.assertFalse(custom_false["ok"])
        with patch.object(fetchers.requests, "get", return_value=_Resp(200, {"balance": 0})):
            custom_zero = fetchers.fetch_custom(item)
        self.assertTrue(custom_zero["ok"])
        self.assertEqual(custom_zero["amount"], 0)


if __name__ == "__main__":
    unittest.main()
