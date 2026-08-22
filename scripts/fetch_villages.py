#!/usr/bin/env python3
"""抓村里人口與村里界線，存進 data_TW/from_moi/。

    python3 scripts/fetch_villages.py

不需要金鑰，兩份都是公開直連。抓下來原樣落地，加工是 prep_villages.py 的事。

── 兩份輸入 ──────────────────────────────────────────────────────────
其一，**村里人口**：內政部戶政司開放資料 ODRP019，逐村里的戶數與男女人口，
分共同生活戶、共同事業戶、單獨生活戶三類。分頁取，每頁2000筆。
民國114年是目前最新的一年（115年查無資料）。

其二，**村里界線**：g0v/twgeojson 的 twVillage1982。全國7,632個里、35.7 MB，
本程式只留臺中的593個，其餘丟掉：這個 repo 只做臺中，扛一份35 MB的全國檔沒有意義。
留下來的每一個 feature 原樣不動，只是少了別的縣市。

── 為什麼不是內政部的官方界線 ────────────────────────────────────────
政府資料開放平臺 dataset 7438「村里界圖(TWD97經緯度)」是現行版（1150624），
唯它的檔案在 tgos.tw，本專案目前的網路環境取不到（回 403）。
拿得到的話，把它換掉即可：臺中現有625個里，g0v 那份1982年版只有593個，
差在民國71年之後被再分割的里，其中太平區最嚴重（39個里對19個多邊形）。
prep_villages.py 會把這件事量出來，並且把畫不準的區降級成區級，不硬畫。
"""
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'data_TW' / 'from_moi'

RIS = 'https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP019/{yyy}?page={page}'
RIS_YEAR = 114          # 民國115年查無資料，114是目前最新
GEO = 'https://raw.githubusercontent.com/g0v/twgeojson/master/json/twVillage1982.geo.json'
CITY = '臺中市'


def get(url, timeout=300):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f'抓 {url} 失敗（HTTP {e.code}）')


def fetch_pop():
    rows, page = [], 1
    while True:
        d = json.loads(get(RIS.format(yyy=RIS_YEAR, page=page), 120))
        if 'responseData' not in d:
            sys.exit(f'戶政司回 {d.get("responseMessage")}，民國{RIS_YEAR}年可能還沒發布')
        rows += d['responseData']
        print(f'  第{page}頁 {len(d["responseData"]):,} 筆　累計 {len(rows):,}／{d["totalDataSize"]}')
        if page >= int(d['totalPage']):
            break
        page += 1
    if len(rows) != int(d['totalDataSize']):
        sys.exit(f'分頁抓到 {len(rows)} 筆，來源說有 {d["totalDataSize"]} 筆，對不上')
    return rows


def fetch_geo():
    g = json.loads(get(GEO))
    n = len(g['features'])
    tc = [f for f in g['features']
          if f['properties']['COUNTYNAME'].replace('台', '臺') == CITY]
    if not tc:
        sys.exit(f'全國 {n} 個里裡找不到{CITY}，來源的欄位可能改了')
    print(f'  全國 {n:,} 個里，留下{CITY}的 {len(tc)} 個')
    return {'type': 'FeatureCollection', 'features': tc}, n


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print(f'村里人口（戶政司 ODRP019，民國{RIS_YEAR}年）')
    rows = fetch_pop()
    (OUT / 'village_pop.json').write_text(json.dumps({
        '_upstream': RIS.format(yyy=RIS_YEAR, page='1..n'),
        '_note': f'內政部戶政司開放資料 ODRP019，民國{RIS_YEAR}年，全國逐村里，原樣不動',
        'data': rows}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    print('\n村里界線（g0v/twgeojson twVillage1982）')
    geo, n = fetch_geo()
    (OUT / 'village_geo_taichung.json').write_text(json.dumps({
        '_upstream': GEO,
        '_note': (f'g0v/twgeojson twVillage1982，全國{n:,}個里，本檔只留{CITY}的'
                  f'{len(geo["features"])}個，留下的 feature 原樣不動。'
                  f'這是民國71年的界線，之後被再分割的里在這裡沒有多邊形'),
        'data': geo}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    for f in ('village_pop.json', 'village_geo_taichung.json'):
        print(f'  {f:30s} {(OUT / f).stat().st_size / 1024:>8,.0f} KB')
    print(f'\n原始檔在 {OUT.relative_to(ROOT)}/，接下來跑 scripts/prep_villages.py')


if __name__ == '__main__':
    main()
