#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cloudi AI 2API 压测 — 设备注册/配额/上传/enhance 全链路并发"""
import base64
import concurrent.futures as cf
import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:8902"
MIN_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


def post(path, body=None, timeout=90):
    req = urllib.request.Request(API + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return {"code": r.status, "ms": int((time.time() - t0) * 1000),
                "data": json.loads(r.read())}
    except urllib.error.HTTPError as e:
        return {"code": e.code, "ms": int((time.time() - t0) * 1000), "data": json.loads(e.read() or b"{}")}
    except Exception as ex:
        return {"code": -1, "ms": int((time.time() - t0) * 1000), "data": {"err": str(ex)}}


def scenario_register(i):
    return post("/v1/session/bootstrap")


def scenario_enhance(i):
    return post("/v1/image/enhance", {"image_b64": base64.b64encode(MIN_JPEG).decode()})


def run(name, fn, n, workers):
    t0 = time.time()
    with cf.ThreadPoolExecutor(workers) as ex:
        rs = list(ex.map(fn, range(n)))
    ok = sum(1 for r in rs if r["code"] == 200 and (r["data"].get("success") is not False))
    biz_ok = sum(1 for r in rs if r["data"].get("success") is True)
    ms = sorted(r["ms"] for r in rs)
    print(f"\n[{name}] n={n} workers={workers}")
    print(f"  HTTP 200 : {ok}/{n}   biz success: {biz_ok}/{n}")
    print(f"  latency  : p50={ms[n//2]}ms  max={ms[-1]}ms  total={int(time.time()-t0)}s")
    errs = {}
    for r in rs:
        if r["code"] != 200 or r["data"].get("success") is False:
            k = str(r["data"])[:90]
            errs[k] = errs.get(k, 0) + 1
    for k, v in list(errs.items())[:5]:
        print(f"  err x{v}: {k}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"Cloudi 2API 压测 against {API}")
    run("register", scenario_register, n, min(n, 8))
    run("enhance", scenario_enhance, min(n, 3), 3)
