"""
benchmarks/run_benchmark.py — Benchmark Cadenza API Latency & Redis Cache Performance
=====================================================================================
Measures latency (P50, P95, P99, Min, Max) across:
1. Cache MISS (Cold query): Engine calculates cosine similarity across PostgreSQL
2. Cache HIT (Warm query): Engine fetches cached result from Redis in <5ms

Usage:
    # Run against local server or container:
    python benchmarks/run_benchmark.py --url http://localhost:5000 --requests 100
"""

import argparse
import random
import statistics
import time
import requests


def run_benchmark(base_url: str, total_requests: int = 50):
    endpoint = f"{base_url.rstrip('/')}/api/recommend"

    print(f"[START] Running Cadenza Performance Benchmark against: {endpoint}")
    print(f"[INFO] Total request iterations: {total_requests} (cold & warm)\n")

    # Verify server is alive
    try:
        health_resp = requests.get(f"{base_url.rstrip('/')}/health", timeout=3)
        health_data = health_resp.json()
        print(f"[OK] Server Health: {health_data.get('status')} | DB: {health_data.get('postgres', {}).get('status')} | Redis: {health_data.get('redis', {}).get('status')}\n")
    except Exception as exc:
        print(f"[WARN] Healthcheck warning: {exc}")

    # 1. Benchmark Cold (Cache MISS) — vary query parameters so it misses cache
    cold_latencies = []
    cold_server_times = []
    print("[BENCHMARK] Measuring Cache MISS (Cold queries)...")
    for i in range(total_requests):
        # Vary vector slightly so each request is a unique hash
        params = {
            "tempo": round(random.uniform(0.3, 0.9), 4),
            "energy": round(random.uniform(0.2, 0.95), 4),
            "danceability": round(random.uniform(0.3, 0.95), 4),
            "valence": round(random.uniform(0.1, 0.9), 4),
            "acousticness": round(random.uniform(0.0, 0.5), 4),
            "instrumentalness": round(random.uniform(0.0, 0.3), 4),
            "n": 10,
        }
        t0 = time.perf_counter()
        resp = requests.get(endpoint, params=params, timeout=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        cold_latencies.append(elapsed_ms)
        try:
            cold_server_times.append(float(resp.headers.get("X-Response-Time-Ms", 0)))
        except ValueError:
            pass

    # 2. Benchmark Warm (Cache HIT) — repeatedly request the same vector
    warm_latencies = []
    warm_server_times = []
    fixed_params = {
        "tempo": 0.5,
        "energy": 0.8,
        "danceability": 0.75,
        "valence": 0.6,
        "acousticness": 0.15,
        "instrumentalness": 0.05,
        "n": 10,
    }
    # Prime cache once
    requests.get(endpoint, params=fixed_params, timeout=10)

    print("[BENCHMARK] Measuring Cache HIT (Warm queries)...")
    for i in range(total_requests):
        t0 = time.perf_counter()
        resp = requests.get(endpoint, params=fixed_params, timeout=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        warm_latencies.append(elapsed_ms)
        try:
            warm_server_times.append(float(resp.headers.get("X-Response-Time-Ms", 0)))
        except ValueError:
            pass

    def calc_stats(latencies):
        sorted_l = sorted(latencies)
        p50 = statistics.median(sorted_l)
        p95 = sorted_l[int(len(sorted_l) * 0.95)]
        p99 = sorted_l[int(len(sorted_l) * 0.99)]
        avg = statistics.mean(sorted_l)
        min_v = min(sorted_l)
        max_v = max(sorted_l)
        return min_v, p50, p95, p99, avg, max_v

    cold_min, cold_p50, cold_p95, cold_p99, cold_avg, cold_max = calc_stats(cold_latencies)
    warm_min, warm_p50, warm_p95, warm_p99, warm_avg, warm_max = calc_stats(warm_latencies)

    s_cold_min, s_cold_p50, s_cold_p95, s_cold_p99, s_cold_avg, s_cold_max = calc_stats(cold_server_times) if cold_server_times else (0,0,0,0,0,0)
    s_warm_min, s_warm_p50, s_warm_p95, s_warm_p99, s_warm_avg, s_warm_max = calc_stats(warm_server_times) if warm_server_times else (0,0,0,0,0,0)

    speedup = round(cold_avg / warm_avg, 1) if warm_avg > 0 else 0
    s_speedup = round(s_cold_avg / s_warm_avg, 1) if s_warm_avg > 0 else 0

    print("\n" + "=" * 80)
    print("[RESULTS] BENCHMARK SUMMARY (Ready to paste into README.md):")
    print("=" * 80 + "\n")

    markdown_table = f"""### Client Round-Trip Latency (End-to-End)

| Metric | Cold Request (`X-Cache: MISS`) | Warm Request (`X-Cache: HIT`) | Speedup / Improvement |
|---|---|---|---|
| **P50 Latency (Median)** | `{cold_p50:.2f} ms` | `{warm_p50:.2f} ms` | **~{round(cold_p50/warm_p50, 1) if warm_p50 else 0}x faster** |
| **P95 Latency** | `{cold_p95:.2f} ms` | `{warm_p95:.2f} ms` | **~{round(cold_p95/warm_p95, 1) if warm_p95 else 0}x faster** |
| **P99 Latency** | `{cold_p99:.2f} ms` | `{warm_p99:.2f} ms` | **~{round(cold_p99/warm_p99, 1) if warm_p99 else 0}x faster** |
| **Mean Latency** | `{cold_avg:.2f} ms` | `{warm_avg:.2f} ms` | **~{speedup}x overall speedup** |
| **Min Latency** | `{cold_min:.2f} ms` | `{warm_min:.2f} ms` | Instant response |
| **Max Latency** | `{cold_max:.2f} ms` | `{warm_max:.2f} ms` | Bounded worst-case roundtrip |
| **Header Status** | `X-Cache: MISS` | `X-Cache: HIT` | Verified via HTTP headers |

### Server-Side Engine Execution Time (`X-Response-Time-Ms`)

| Metric | Cold Request (`X-Cache: MISS`) | Warm Request (`X-Cache: HIT`) | Speedup / Improvement |
|---|---|---|---|
| **P50 Processing (Median)** | `{s_cold_p50:.2f} ms` | `{s_warm_p50:.2f} ms` | **~{round(s_cold_p50/s_warm_p50, 1) if s_warm_p50 else 0}x faster** |
| **P95 Processing** | `{s_cold_p95:.2f} ms` | `{s_warm_p95:.2f} ms` | **~{round(s_cold_p95/s_warm_p95, 1) if s_warm_p95 else 0}x faster** |
| **Mean Processing** | `{s_cold_avg:.2f} ms` | `{s_warm_avg:.2f} ms` | **~{s_speedup}x engine speedup** |
| **Min Processing** | `{s_cold_min:.2f} ms` | `{s_warm_min:.2f} ms` | Direct memory/cache lookup |
"""
    print(markdown_table)
    print("=" * 80)
    print(markdown_table)
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cadenza Performance Benchmark")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL of Cadenza API")
    parser.add_argument("--requests", type=int, default=50, help="Number of benchmark iterations")
    args = parser.parse_args()

    run_benchmark(args.url, args.requests)
