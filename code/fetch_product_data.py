import json
import os
import time
from datetime import datetime, timedelta
from lingxing_client import LingXingClient, RateLimitError

# ============================================================
DATE_A = "2026-06-01"  # 日期A (YYYY-MM-DD)

# 输出文件路径
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "result.json")
PARTIAL_OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "result.partial.json")
FAILED_REQUESTS_FILE = os.path.join(os.path.dirname(__file__), "failed_product_requests.json")
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "fetch_progress.json")
SHOP_RECORDS_FILE = os.path.join(os.path.dirname(__file__), "shop_records.jsonl")
PROBLEM_SHOPS_FILE = os.path.join(os.path.dirname(__file__), "problem_shops.json")

# 单店铺请求：sid 始终按文档传字符串，例如 "sid": "5608"。
REQUEST_MODE = "single_shop"
PAGE_LENGTH = 1000
RATE_LIMIT_COOLDOWN_SECONDS = 10
FINAL_RETRY_COOLDOWNS_SECONDS = [30, 60, 120]
# ============================================================


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message):
    print(message, flush=True)


def write_json_file(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_json_line(path, data):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def init_progress():
    return {
        "started_at": now_text(),
        "updated_at": now_text(),
        "date_a": DATE_A,
        "request_mode": REQUEST_MODE,
        "page_length": PAGE_LENGTH,
        "completed_shops": [],
        "failed_shops": [],
        "retry_failed_shops": [],
        "final_failed": []
    }


def save_progress(progress):
    progress["updated_at"] = now_text()
    write_json_file(PROGRESS_FILE, progress)


def save_partial_result(asin_data):
    write_json_file(PARTIAL_OUTPUT_FILE, list(asin_data.values()))


def save_shop_records(range_label, start_date, end_date, shop, records, retried=False):
    append_json_line(SHOP_RECORDS_FILE, {
        "saved_at": now_text(),
        "range_label": range_label,
        "start_date": start_date,
        "end_date": end_date,
        "sid": str(shop["sid"]),
        "shop_name": shop.get("name", ""),
        "records_count": len(records),
        "retried": retried,
        "records": records
    })


def clean_record(item):
    """清洗单条记录，只提取需要的字段: asin, principal_names, ad_cvr, volume_cvr, cvr, ctr"""
    asin = item.get('asin')
    if not asin:
        asins = item.get('asins', [])
        if asins and len(asins) > 0:
            asin = asins[0].get('asin')

    if not asin:
        return None

    principal_names = item.get('principal_names', [])
    if isinstance(principal_names, str):
        principal_names = [principal_names] if principal_names else []
    elif not isinstance(principal_names, list):
        principal_names = []

    def get_float(v):
        try:
            return round(float(v), 4) if v is not None else None
        except (ValueError, TypeError):
            return None

    return {
        'asin': asin,
        'principal_names': principal_names,
        'ad_cvr': get_float(item.get('ad_cvr')),
        'volume_cvr': get_float(item.get('volume_cvr')),
        'cvr': get_float(item.get('cvr')),
        'ctr': get_float(item.get('ctr'))
    }


def get_all_shops(client):
    """获取所有店铺列表"""
    data = client.get("/erp/sc/data/seller/lists")
    shops = []
    for item in (data or []):
        sid = item.get('sid')
        name = item.get('name', '')
        if sid:
            shops.append({'sid': str(sid), 'name': name})
    return shops


def fetch_product_performance_shop(client, shop, start_date, end_date):
    """按文档的单店铺方式获取商品表现数据：sid 传字符串。"""
    all_records = []
    sid = str(shop["sid"])
    offset = 0

    while True:
        business_params = {
            "offset": offset,
            "length": PAGE_LENGTH,
            "sort_field": "volume",
            "sort_type": "desc",
            "sid": sid,
            "start_date": start_date,
            "end_date": end_date,
            "summary_field": "asin"
        }

        data = client.post("/bd/productPerformance/openApi/asinList", body=business_params)
        if not data:
            break

        records = data.get('list', [])
        total = data.get('total', 0)

        for item in records:
            cleaned = clean_record(item)
            if cleaned:
                all_records.append(cleaned)

        if offset + PAGE_LENGTH >= total or len(records) == 0:
            break
        offset += PAGE_LENGTH

    return all_records


def describe_shop(shop):
    name = shop.get("name", "")
    if name:
        return f"{shop['sid']}({name})"
    return str(shop["sid"])


def make_failed_request(range_label, start_date, end_date, shop, error):
    error_code = getattr(error, "code", None)
    return {
        "range_label": range_label,
        "start_date": start_date,
        "end_date": end_date,
        "sid": str(shop["sid"]),
        "shop_name": shop.get("name", ""),
        "error_code": str(error_code) if error_code is not None else None,
        "error": str(error),
        "failed_at": now_text()
    }


def build_problem_shops(failed_requests):
    problem_map = {}
    for item in failed_requests:
        sid = str(item.get("sid", ""))
        if not sid:
            continue
        if sid not in problem_map:
            problem_map[sid] = {
                "sid": sid,
                "shop_name": item.get("shop_name", ""),
                "fail_count": 0,
                "errors": []
            }
        problem_map[sid]["fail_count"] += 1
        problem_map[sid]["errors"].append({
            "range_label": item.get("range_label"),
            "start_date": item.get("start_date"),
            "end_date": item.get("end_date"),
            "error_code": item.get("error_code"),
            "error": item.get("error"),
            "failed_at": item.get("failed_at")
        })

    def sort_key(item):
        sid = item["sid"]
        sid_key = (0, int(sid)) if sid.isdigit() else (1, sid)
        return (-item["fail_count"], sid_key)

    return sorted(problem_map.values(), key=sort_key)


def retry_failed_shops(client, failed_shops, progress=None):
    """所有店铺先跑完，再回头多轮补跑失败店铺。"""
    recovered_records = []
    final_failed = []
    pending = list(failed_shops)

    for round_index, cooldown in enumerate(FINAL_RETRY_COOLDOWNS_SECONDS, start=1):
        if not pending:
            break

        log(f"  [补跑等待] 第 {round_index} 轮补跑前冷却 {cooldown} 秒，待补跑 {len(pending)} 个店铺")
        time.sleep(cooldown)

        next_pending = []
        for item in pending:
            shop = item["shop"]
            range_label = item["range_label"]
            start_date = item["start_date"]
            end_date = item["end_date"]

            log(f"  [补跑] 第 {round_index} 轮 {range_label} 店铺 {describe_shop(shop)}")
            try:
                records = fetch_product_performance_shop(client, shop, start_date, end_date)
                recovered_records.extend(records)
                save_shop_records(range_label, start_date, end_date, shop, records, retried=True)
                log(f"  [补跑成功] 第 {round_index} 轮 {range_label} 店铺 {describe_shop(shop)}，记录 {len(records)} 条")
                if progress is not None:
                    progress["completed_shops"].append({
                        "range_label": range_label,
                        "start_date": start_date,
                        "end_date": end_date,
                        "sid": str(shop["sid"]),
                        "shop_name": shop.get("name", ""),
                        "records_count": len(records),
                        "retried": True,
                        "retry_round": round_index,
                        "completed_at": now_text()
                    })
                    save_progress(progress)
            except Exception as e:
                failed = make_failed_request(range_label, start_date, end_date, shop, e)
                item["last_failed"] = failed
                next_pending.append(item)
                if isinstance(e, RateLimitError):
                    log(f"  [补跑仍限流] 第 {round_index} 轮 {range_label} 店铺 {describe_shop(shop)}: {e}")
                else:
                    log(f"  [补跑失败] 第 {round_index} 轮 {range_label} 店铺 {describe_shop(shop)}: {e}")
                if progress is not None:
                    retry_failed = dict(failed)
                    retry_failed["retry_round"] = round_index
                    progress["retry_failed_shops"].append(retry_failed)
                    save_progress(progress)

        pending = next_pending

    for item in pending:
        failed = item.get("last_failed") or make_failed_request(
            item["range_label"], item["start_date"], item["end_date"], item["shop"], Exception("补跑失败")
        )
        final_failed.append(failed)
        if progress is not None:
            progress["final_failed"].append(failed)
            save_progress(progress)

    return recovered_records, final_failed


def get_product_performance_by_shop(client, shops, start_date, end_date, range_label, progress=None):
    """逐个店铺获取数据；失败店铺先缓存，全部店铺跑完后再补跑。"""
    all_records = []
    failed_shops = []
    total_shops = len(shops)

    for index, shop in enumerate(shops, start=1):
        log(f"  [请求] 店铺 {index}/{total_shops}: {describe_shop(shop)}")
        try:
            records = fetch_product_performance_shop(client, shop, start_date, end_date)
            all_records.extend(records)
            save_shop_records(range_label, start_date, end_date, shop, records)
            log(f"  [成功] 店铺 {index}/{total_shops}: {describe_shop(shop)}，记录 {len(records)} 条")
            if progress is not None:
                progress["completed_shops"].append({
                    "range_label": range_label,
                    "start_date": start_date,
                    "end_date": end_date,
                    "shop_index": index,
                    "total_shops": total_shops,
                    "sid": str(shop["sid"]),
                    "shop_name": shop.get("name", ""),
                    "records_count": len(records),
                    "completed_at": now_text()
                })
                save_progress(progress)
        except Exception as e:
            if isinstance(e, RateLimitError):
                log(f"  [限流缓存] 店铺 {index}/{total_shops}: {describe_shop(shop)} 遇到限流，先跳过: {e}")
                time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
            else:
                log(f"  [先缓存] 店铺 {index}/{total_shops}: {describe_shop(shop)} 请求失败: {e}")

            failed_shop = {
                "range_label": range_label,
                "start_date": start_date,
                "end_date": end_date,
                "shop": shop,
                "sid": str(shop["sid"]),
                "shop_name": shop.get("name", ""),
                "shop_index": index,
                "total_shops": total_shops,
                "error_code": str(getattr(e, "code", "")) if getattr(e, "code", None) is not None else None,
                "error": str(e),
                "failed_at": now_text()
            }
            failed_shops.append(failed_shop)
            if progress is not None:
                progress["failed_shops"].append(failed_shop)
                save_progress(progress)

    final_failed = []
    if failed_shops:
        log(f"\n  开始补跑之前失败的 {len(failed_shops)} 个店铺...")
        recovered_records, final_failed = retry_failed_shops(client, failed_shops, progress)
        all_records.extend(recovered_records)

    return all_records, final_failed


def main():
    for path in (PARTIAL_OUTPUT_FILE, FAILED_REQUESTS_FILE, PROGRESS_FILE, SHOP_RECORDS_FILE, PROBLEM_SHOPS_FILE):
        if os.path.exists(path):
            os.remove(path)

    date_a = datetime.strptime(DATE_A, "%Y-%m-%d")
    today = datetime.now().date()

    # 检查：如果今天在日期A的7天内，表示时间还没到，不进行请求
    if today < (date_a + timedelta(days=7)).date():
        log(f"时间还没到，不进行请求")
        log(f"(日期A={DATE_A}, A+7天={(date_a + timedelta(days=7)).strftime('%Y-%m-%d')}, 今天={today})")
        return

    # 定义3个请求的日期范围
    date_ranges = [
        ("7天前",  (date_a - timedelta(days=7)).strftime("%Y-%m-%d"), DATE_A),
        ("7天后",  DATE_A, (date_a + timedelta(days=7)).strftime("%Y-%m-%d")),
        ("14天内", (date_a - timedelta(days=7)).strftime("%Y-%m-%d"), (date_a + timedelta(days=7)).strftime("%Y-%m-%d")),
    ]

    log(f"日期A: {DATE_A}")
    for label, start, end in date_ranges:
        log(f"  {label}: {start} ~ {end}")
    log("")

    client = LingXingClient()
    progress = init_progress()
    save_progress(progress)

    # 获取所有店铺
    log("正在获取店铺列表...")
    shops = get_all_shops(client)
    progress["shops_count"] = len(shops)
    progress["shops"] = shops
    save_progress(progress)
    log(f"获取到 {len(shops)} 个店铺\n")

    # 按 ASIN 汇总数据
    asin_data = {}
    all_failed_requests = []

    # 对每个日期范围分别请求（单店铺请求，失败店铺后置补跑）
    for range_label, start_date, end_date in date_ranges:
        log(f"\n{'='*60}")
        log(f"{range_label}: {start_date} ~ {end_date}")
        log(f"{'='*60}")

        records, failed_requests = get_product_performance_by_shop(
            client, shops, start_date, end_date, range_label, progress
        )
        all_failed_requests.extend(failed_requests)
        log(f"获取 {len(records)} 条记录")

        for r in records:
            asin = r['asin']
            if asin not in asin_data:
                asin_data[asin] = {
                    'asin': asin,
                    'principal_names': r['principal_names'],
                    'ad_cvr': {},
                    'volume_cvr': {},
                    'cvr': {},
                    'ctr': {}
                }

            asin_data[asin]['ad_cvr'][range_label] = r['ad_cvr']
            asin_data[asin]['volume_cvr'][range_label] = r['volume_cvr']
            asin_data[asin]['cvr'][range_label] = r['cvr']
            asin_data[asin]['ctr'][range_label] = r['ctr']
        save_partial_result(asin_data)

    # 构建输出
    result = list(asin_data.values())

    # 写入 JSON 文件
    write_json_file(OUTPUT_FILE, result)
    write_json_file(FAILED_REQUESTS_FILE, all_failed_requests)
    problem_shops = build_problem_shops(
        progress["failed_shops"] + progress["retry_failed_shops"] + all_failed_requests
    )
    write_json_file(PROBLEM_SHOPS_FILE, problem_shops)

    progress["finished_at"] = now_text()
    progress["result_count"] = len(result)
    progress["final_failed_count"] = len(all_failed_requests)
    progress["problem_shop_count"] = len(problem_shops)
    save_progress(progress)

    log(f"\n{'='*60}")
    log(f"完成！共 {len(result)} 个ASIN，结果已输出到: {OUTPUT_FILE}")
    if all_failed_requests:
        log(f"仍有 {len(all_failed_requests)} 次单店铺请求失败，已输出到: {FAILED_REQUESTS_FILE}")
        log(f"问题店铺汇总已输出到: {PROBLEM_SHOPS_FILE}")


if __name__ == "__main__":
    main()
