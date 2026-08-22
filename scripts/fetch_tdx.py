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
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'data_TW' / 'from_tdx'
ENV = ROOT / '.env'

TOKEN_URL = 'https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token'
BASE = 'https://tdx.transportdata.tw/api/basic/v2'

# (檔名, 路徑, 這份資料補的是哪一個缺口)
ENDPOINTS = [
    ('metro_network_tmrt.json', '/Rail/Metro/Network/TMRT',
     '臺中捷運的路線與車站關聯。補上目前完全缺席的綠線'),
    ('metro_station_tmrt.json', '/Rail/Metro/Station/TMRT',
     '臺中捷運車站，含經緯度'),
    ('metro_shape_tmrt.json', '/Rail/Metro/Shape/TMRT',
     '臺中捷運的路線線形（WKT）。畫得出綠線的實際走向'),
    ('thsr_station.json', '/Rail/THSR/Station',
     '高鐵車站含經緯度。補上目前有線形沒有站點的高鐵臺中站'),
    ('tra_station.json', '/Rail/TRA/Station',
     '臺鐵車站。TDX 這一份含 StationClass，那就是官方站等'),
    # 公車。上一次跑 /Bus/Station/City/Taichung 失敗，所以這裡把站位的兩種路徑
    # （Station 是站位群、Stop 是單一站牌）與路線、線形、班距都列上，
    # 哪一個通就用哪一個；失敗的會列在結尾，不影響其餘端點。
    ('bus_stop_taichung.json', '/Bus/Stop/City/Taichung',
     '臺中公車站牌（單一站牌，含經緯度）'),
    ('bus_station_taichung.json', '/Bus/Station/City/Taichung',
     '臺中公車站位（同一路口的站牌群）'),
    ('bus_route_taichung.json', '/Bus/Route/City/Taichung',
     '臺中公車路線清單'),
    ('bus_shape_taichung.json', '/Bus/Shape/City/Taichung',
     '臺中公車路線線形。要畫路線圖就靠這一份'),
    ('bus_frequency_taichung.json', '/Bus/Frequency/City/Taichung',
     '臺中公車班距（每個時段的最小與最大班距分鐘數）。線寬按頻率畫粗細就靠這一份'),
]


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


def grab(tok, path):
    url = f'{BASE}{path}?%24format=JSON'
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {tok}', 'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def main():
    tok = token(*creds())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'README.md').write_text(
        '# TDX 原始檔\n\n'
        '由 `scripts/fetch_tdx.py` 抓下來，原樣存放，不做加工。\n'
        '金鑰不在這裡也不在版控裡，見專案 README 的「TDX 金鑰放哪裡」。\n\n'
        + '\n'.join(f'- `{n}` — {why}' for n, _, why in ENDPOINTS) + '\n',
        encoding='utf-8')

    ok, bad = 0, []
    for name, path, why in ENDPOINTS:
        try:
            blob = grab(tok, path)
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
        print('失敗的端點（TDX 路徑偶爾改版，對照官方文件調整 ENDPOINTS）：')
        for n, e in bad:
            print(f'  {n}　{e}')
    print(f'\n原始檔在 {OUT.relative_to(ROOT)}/，接下來跑 scripts/prep_rail.py 併進地圖')


if __name__ == '__main__':
    main()
