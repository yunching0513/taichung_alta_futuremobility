#!/usr/bin/env python3
"""從交通部TDX抓臺中的軌道與公車資料，存進 data_TW/from_tdx/。

    export TDX_CLIENT_ID=...
    export TDX_CLIENT_SECRET=...
    python3 scripts/fetch_tdx.py

金鑰只從環境變數讀，**不接受命令列參數**：命令列會留在 shell 的歷史紀錄裡。
本機要方便的話，把兩行寫進專案根目錄的 .env（已列入 .gitignore），本程式會自己讀。

抓下來的是原始 JSON，原樣落進 data_TW/from_tdx/，不做任何加工。
加工是 prep_*.py 的事（見 README 的資料流向）。
這支程式**不在 CI 的建置流程裡**：建置只讀已經抓下來並納入版控的原始檔，
所以平常的部署不需要金鑰。要更新資料才手動跑這一支。

── TDX 的取用方式 ──────────────────────────────────────────────────────
先用 client_credentials 換一個 access token（有效期一小時），
之後每一個請求帶 Authorization: Bearer。免費會員有流量上限，
所以本程式一次把需要的端點抓完就停，不做輪詢。

端點清單見 ENDPOINTS。臺中捷運的營運業者代碼是 TMRT。
若某個端點回 404 或 401，本程式會記下來繼續抓下一個，不中止：
TDX 的路徑偶爾會改版，一個端點失效不該讓其餘的資料也抓不到。

── 為什麼要退避與分頁 ────────────────────────────────────────────────
民國115年8月22日那一次，五個軌道端點全數成功，五個公車端點全數回 HTTP 429。
429 是「請求太密集」，不是路徑錯了：軌道那五個把該分鐘的額度用完，
公車那五個接著送出就全被擋下。因此本程式做三件事：
每兩個請求之間至少間隔 GAP 秒、遇 429 依 Retry-After 退避重試、
以及對筆數多的端點（公車路線與線形動輒數千筆）改用 $top／$skip 分頁抓。
分頁抓回來的會重新組成一個 JSON 陣列再寫檔，因此那幾份不是逐位元組的原樣，
唯每一筆記錄本身沒有被加工過。

要只補其中幾份，設 TDX_ONLY，用逗號分隔檔名（額度有限時很有用）：
    TDX_ONLY=bus_shape_taichung.json,bus_frequency_taichung.json
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'data_TW' / 'from_tdx'
ENV = ROOT / '.env'

TOKEN_URL = 'https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token'
BASE = 'https://tdx.transportdata.tw/api/basic/v2'

# (檔名, 路徑, 這份資料補的是哪一個缺口, 要不要分頁)
ENDPOINTS = [
    ('metro_network_tmrt.json', '/Rail/Metro/Network/TMRT',
     '臺中捷運的路線與車站關聯。補上目前完全缺席的綠線', False),
    ('metro_station_tmrt.json', '/Rail/Metro/Station/TMRT',
     '臺中捷運車站，含經緯度', False),
    ('metro_shape_tmrt.json', '/Rail/Metro/Shape/TMRT',
     '臺中捷運的路線線形（WKT）。畫得出綠線的實際走向', False),
    ('thsr_station.json', '/Rail/THSR/Station',
     '高鐵車站含經緯度。補上目前有線形沒有站點的高鐵臺中站', False),
    ('tra_station.json', '/Rail/TRA/Station',
     '臺鐵車站。TDX 這一份含 StationClass，那就是官方站等', False),
    # 公車。站位有兩種路徑（Station 是同一路口的站牌群、Stop 是單一站牌），兩個都列，
    # 哪一個通就用哪一個。這五份筆數都是數千起跳，一律分頁。
    ('bus_stop_taichung.json', '/Bus/Stop/City/Taichung',
     '臺中公車站牌（單一站牌，含經緯度）', True),
    ('bus_station_taichung.json', '/Bus/Station/City/Taichung',
     '臺中公車站位（同一路口的站牌群）', True),
    ('bus_route_taichung.json', '/Bus/Route/City/Taichung',
     '臺中公車路線清單', True),
    ('bus_shape_taichung.json', '/Bus/Shape/City/Taichung',
     '臺中公車路線線形。要畫路線圖就靠這一份', True),
    # 班距原本填 /Bus/Frequency/City/Taichung，帶著有效 token 仍然回 404，
    # 代表那個路徑不服務市區公車（另外兩個公車端點同一個 token 都通）。
    # 市區公車的班距與時刻表在 /Bus/Schedule：有固定班距的路線給 Frequencys
    # （StartTime、EndTime、MinHeadwayMins、MaxHeadwayMins），
    # 走固定時刻表的路線給 Timetables，兩種都算得出每小時班次。
    ('bus_schedule_taichung.json', '/Bus/Schedule/City/Taichung',
     '臺中公車班表與班距。線寬按頻率畫粗細就靠這一份', True),
    # 班表的 StopTimes 只給起站那一筆（11,516 班裡有 11,484 班如此），
    # 所以「某一區每天有幾次車停靠」算不出來，只能算出「以該區為起點發幾班」。
    # 停靠站序在 StopOfRoute：每條子路線的完整站序，
    # 乘上那條子路線的班次，才是該區的停靠班次。
    ('bus_stopofroute_taichung.json', '/Bus/StopOfRoute/City/Taichung',
     '臺中公車每條子路線的完整停靠站序。區級的停靠班次靠它乘班次算出來', True),
]

PAGE = 1000      # 一頁幾筆。TDX 對 $top 有上限，取一個保守值
GAP = 2.0        # 兩個請求之間至少隔幾秒。429 就是踩到這個節奏才發生的
TRIES = 5        # 遇 429 最多重試幾次


def creds():
    cid = os.environ.get('TDX_CLIENT_ID')
    sec = os.environ.get('TDX_CLIENT_SECRET')
    if (not cid or not sec) and ENV.exists():
        for line in ENV.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            v = v.strip().strip('"').strip("'")
            if k.strip() == 'TDX_CLIENT_ID' and not cid:
                cid = v
            elif k.strip() == 'TDX_CLIENT_SECRET' and not sec:
                sec = v
    if not cid or not sec:
        sys.exit(
            '找不到金鑰。兩種給法擇一：\n'
            '  export TDX_CLIENT_ID=... ; export TDX_CLIENT_SECRET=...\n'
            '  或在專案根目錄建一個 .env，寫上那兩行（.env 已列入 .gitignore）\n'
            '金鑰到 https://tdx.transportdata.tw 註冊會員後於「資料服務」頁申請。')
    return cid, sec


def token(cid, sec):
    body = urllib.parse.urlencode({
        'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': sec,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())['access_token']
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode('utf-8', 'replace')
        sys.exit(f'換 token 失敗（HTTP {e.code}）：{detail}\n'
                 f'400 invalid_client 通常是 client_id 或 secret 抄錯或已失效。')


def get(tok, url):
    """抓一個網址，遇 429 退避重試。回傳原始位元組。"""
    for i in range(TRIES):
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {tok}', 'Accept-Encoding': 'identity'})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == TRIES - 1:
                raise
            # TDX 有給 Retry-After 就聽它的，沒給就指數退避
            try:
                wait = float(e.headers.get('Retry-After') or 0)
            except ValueError:
                wait = 0
            wait = min(max(wait, GAP * 2 ** i), 90)
            print(f'      429 請求太密集，等 {wait:.0f} 秒再試（第 {i + 1} 次）')
            time.sleep(wait)


def grab(tok, path, paged):
    if not paged:
        return get(tok, f'{BASE}{path}?%24format=JSON')
    # 分頁：一直往下翻，直到某一頁不滿 PAGE 筆為止。
    # 回傳的是重新組起來的陣列，每一筆記錄本身原樣不動。
    rows = []
    while True:
        url = (f'{BASE}{path}?%24format=JSON'
               f'&%24top={PAGE}&%24skip={len(rows)}')
        page = json.loads(get(tok, url))
        if not isinstance(page, list):
            return json.dumps(page, ensure_ascii=False).encode()   # 不是陣列就別硬翻
        rows += page
        print(f'      第 {len(rows) // PAGE + (0 if len(page) == PAGE else 1)} 頁，'
              f'累計 {len(rows):,} 筆')
        if len(page) < PAGE:
            return json.dumps(rows, ensure_ascii=False).encode()
        time.sleep(GAP)


def main():
    todo = {n.strip() for n in os.environ.get('TDX_ONLY', '').split(',') if n.strip()}
    known = {n for n, _, _, _ in ENDPOINTS}
    if todo - known:
        sys.exit(f'TDX_ONLY 裡有不認識的檔名：{sorted(todo - known)}\n'
                 f'可用的是：{sorted(known)}')
    if todo:
        print(f'只抓 {len(todo)} 個端點（TDX_ONLY）\n')
    tok = token(*creds())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'README.md').write_text(
        '# TDX 原始檔\n\n'
        '由 `scripts/fetch_tdx.py` 抓下來，原樣存放，不做加工。\n'
        '金鑰不在這裡也不在版控裡，見專案 README 的「TDX 金鑰放哪裡」。\n\n'
        + '\n'.join(f'- `{n}` — {why}' for n, _, why, _ in ENDPOINTS) + '\n',
        encoding='utf-8')

    ok, bad, first = 0, [], True
    for name, path, why, paged in ENDPOINTS:
        if todo and name not in todo:
            continue
        if not first:
            time.sleep(GAP)      # 額度是按時間算的，端點之間不要連著送
        first = False
        try:
            blob = grab(tok, path, paged)
        except urllib.error.HTTPError as e:
            bad.append((name, f'HTTP {e.code}'))
            print(f'  ✗ {name:30s} HTTP {e.code}')
            continue
        except Exception as e:                                    # noqa: BLE001
            bad.append((name, type(e).__name__))
            print(f'  ✗ {name:30s} {type(e).__name__}')
            continue
        (OUT / name).write_bytes(blob)
        n = len(json.loads(blob)) if blob.lstrip()[:1] == b'[' else '－'
        ok += 1
        print(f'  ✓ {name:30s} {len(blob):>9,}B　{n} 筆　{why}')

    print(f'\n成功 {ok} ・ 失敗 {len(bad)}')
    if bad:
        print('失敗的端點。429 是額度或節奏問題，隔一段時間用 TDX_ONLY 單獨補抓；'
              '404 才是路徑改版，要對照官方文件調整 ENDPOINTS：')
        for n, e in bad:
            print(f'  {n}　{e}')
    print(f'\n原始檔在 {OUT.relative_to(ROOT)}/，接下來跑 scripts/prep_rail.py 併進地圖')


if __name__ == '__main__':
    main()
