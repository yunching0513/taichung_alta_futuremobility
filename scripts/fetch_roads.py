#!/usr/bin/env python3
"""抓公路路網與臺鐵各站進出站人次，存進 data_TW/。

    python3 scripts/fetch_roads.py

不需要金鑰。抓下來原樣落地，加工是 prep_*.py 的事。

── 兩份輸入 ──────────────────────────────────────────────────────────
其一，**公路路網**：yunching0513/taiwan-mobility-atlas 的 data/taichung.highways.geojson。
上游是公路局的路線圖資，properties 自帶 class 欄位，分國道、快速公路、省道三級。
**市區道路不在裡面**：那是另一個量級的資料（一個城市數萬條路段），
公路局的公開圖資也只到省道。缺這一級的事寫在 docs/sources.md 與版面上。

其二，**臺鐵每日各站進出站人數**：交通部臺鐵公司經 data.gov.tw 釋出（dataset 8792）。
全臺每日逐站，本程式只留臺中境內那23站，其餘丟掉：這個 repo 只做臺中。
高鐵與臺中捷運沒有對應的公開檔案可取：交通部統計查詢網 stat.motc.gov.tw
與臺中市政府資料中心 datacenter.taichung.gov.tw 在本專案目前的網路環境都連不到，
因此那兩個系統的車站在版面上是 null，不是0，也不會拿臺鐵的數字去頂替。
"""
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ATLAS = pathlib.Path('/home/user/yunching0513/taiwan-mobility-atlas')
OUT_R = ROOT / 'data_TW' / 'from_mobility_atlas'
OUT_T = ROOT / 'data_TW' / 'from_tra'

TRA_URL = ('https://ods.railway.gov.tw/tra-ods-web/ods/download/'
           'dataResource/8ae4cabf6973990e0169947ed32454b9')
TRIES = 4       # 這個網址偶爾會 Connection reset，重試就過


def get(url):
    for i in range(TRIES):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                return r.read()
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            if i == TRIES - 1:
                sys.exit(f'抓 {url} 失敗：{e}')
            print(f'    第{i + 1}次失敗（{type(e).__name__}），重試')


def main():
    OUT_R.mkdir(parents=True, exist_ok=True)
    OUT_T.mkdir(parents=True, exist_ok=True)

    # ── 公路 ──
    src = ATLAS / 'data' / 'taichung.highways.geojson'
    if not src.exists():
        sys.exit(f'找不到 {src}。先 git clone yunching0513/taiwan-mobility-atlas 到 {ATLAS}')
    sha = subprocess.run(['git', '-C', str(ATLAS), 'rev-parse', '--short', 'HEAD'],
                         capture_output=True, text=True).stdout.strip()
    geo = json.loads(src.read_text(encoding='utf-8'))
    (OUT_R / 'taichung_highways.json').write_text(json.dumps({
        '_upstream': f'yunching0513/taiwan-mobility-atlas @ {sha}　data/taichung.highways.geojson',
        '_note': ('公路局路線圖資，properties 的 class 分國道、快速公路、省道三級，原樣不動。'
                  '市區道路不在這一份裡'),
        'data': geo}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'  公路 {len(geo["features"]):,} 段')

    # ── 臺鐵進出站人次 ──
    print('臺鐵每日各站進出站人數（data.gov.tw 8792）')
    rows = json.loads(get(TRA_URL))
    print(f'  全臺 {len(rows):,} 筆')
    rail = ROOT / 'data' / 'tc_rail.json'
    if not rail.exists():
        sys.exit('先跑 python3 scripts/prep_rail.py，本程式要用它的車站代碼來篩選')
    codes = {s['id'] for s in json.loads(rail.read_text(encoding='utf-8'))['stops']
             if s['sys'] == 'tra'}
    tc = [r for r in rows if r.get('staCode') in codes]
    if not tc:
        sys.exit('篩不出臺中的車站，staCode 與 TDX 的 StationID 對不上')
    days = sorted({r['trnOpDate'] for r in tc})
    print(f'  臺中 {len(codes)} 站、{len(tc):,} 筆、{days[0]} 至 {days[-1]}')
    (OUT_T / 'tra_station_ridership.json').write_text(json.dumps({
        '_upstream': TRA_URL,
        '_note': (f'臺鐵每日各站進出站人數，data.gov.tw dataset 8792。'
                  f'全臺 {len(rows):,} 筆，本檔只留臺中境內那 {len(codes)} 站的 {len(tc):,} 筆，'
                  f'留下的每一筆原樣不動。期間 {days[0]} 至 {days[-1]}'),
        'data': tc}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    for p in (OUT_R / 'taichung_highways.json', OUT_T / 'tra_station_ridership.json'):
        print(f'  {p.name:32s} {p.stat().st_size / 1024:>8,.0f} KB')


if __name__ == '__main__':
    main()
