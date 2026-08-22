#!/usr/bin/env python3
"""把臺中境內的公路路網整理成一份中間檔。

    python3 scripts/prep_roads.py

輸入 data_TW/from_mobility_atlas/taichung_highways.json（由 fetch_roads.py 抓下來），
上游是公路局的路線圖資，properties 自帶 class 欄位。
輸出 data/tc_roads.json：分級、裁切至市界、抽稀過的線形。

── 分幾級，為什麼 ────────────────────────────────────────────────────
來源檔分三級：國道、快速公路、省道。版面照這三級畫，線寬與顏色都跟著等級走，
因為**公路的等級就是它的設計速度與出入口密度**，而那兩件事決定了它旁邊的人怎麼移動、
以及一次碰撞的動能有多大。第07節的A1死亡率與這一層放在一起看才有意義。

**市區道路不在這一份裡，而且短期內接不進來。** 公路局的公開圖資只到省道；
市區道路是市政府的權責，臺中市政府資料中心 datacenter.taichung.gov.tw
在本專案目前的網路環境連不到。這一級缺席的後果要講清楚：
圖上看起來沒有路的地方**不是沒有路**，是那些路不在這一份資料的範圍內。
在那之前，第02節的公車路線疊圖是市區道路最接近的替代：
696條子路線走的就是市區的主要道路。

── 裁切與抽稀 ────────────────────────────────────────────────────────
來源檔叫 taichung.highways，唯它是按「路線行經臺中」挑出來的整條路線，
不是按市界裁切的：台3線從苗栗一路到南投都在裡面。因此本程式仍然做市界裁切，
否則國道1號會從基隆畫到高雄，把整張圖的比例尺毀掉。
抽稀門檻與公車路線同一個值，理由也同一個：這張圖1120單位寬、跨約0.6度經度，
一個單位約0.00054度，0.0012度約2.4個像素。
"""
import collections
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'data_TW' / 'from_mobility_atlas' / 'taichung_highways.json'
DIST = ROOT / 'data' / 'tc_districts.json'
OUT = ROOT / 'data' / 'tc_roads.json'

THIN = 0.0012          # 約130公尺、圖上約2.4個像素
NDP = 4                # 座標小數位數，約11公尺
MIN_PTS = 2

# 來源檔的 class 值 → 版面用的分級。順序就是畫的順序：等級低的先畫，高的疊在上面。
CLASSES = [
    ('省道', '省道', '#8A8A8A', 1.0),
    ('快速公路', '快速公路', '#3A7CC3', 1.8),
    ('國道', '國道', '#1A1A1A', 2.6),
]
KNOWN = {c[0] for c in CLASSES}


def zh(t):
    """只正規化「台中」與「台灣」兩個詞，理由同 prep_crash.py 的同名函式：
    路線名與交流道名會顯示在 tooltip 上（例如「台中環線」「台中交流道」），
    而這兩個詞的官方寫法都是「臺」。路線編號（台1、台3）是識別碼，不動。"""
    return (t or '').replace('台中', '臺中').replace('台灣', '臺灣')


def inside(pt, rings):
    x, y = pt
    hit = False
    for r in rings:
        n = len(r)
        for i in range(n):
            x1, y1 = r[i]
            x2, y2 = r[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                if x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                    hit = not hit
    return hit


def thin(line):
    if len(line) < 3:
        return [[round(c, NDP) for c in p] for p in line]
    out = [line[0]]
    for p in line[1:-1]:
        q = out[-1]
        if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= THIN ** 2:
            out.append(p)
    out.append(line[-1])
    return [[round(c, NDP) for c in p] for p in out]


def clip(seg, rings):
    """留下落在市界內的連續點列，兩端各多留一點讓線接到邊界。"""
    kept, run = [], []
    flags = [inside(pt, rings) for pt in seg]
    for i, (pt, ok) in enumerate(zip(seg, flags)):
        if ok:
            if not run and i > 0:
                run.append(seg[i - 1])
            run.append(pt)
        elif run:
            run.append(pt)
            if len(run) > MIN_PTS - 1:
                kept.append(thin(run))
            run = []
    if len(run) > MIN_PTS - 1:
        kept.append(thin(run))
    return kept


def main():
    if not SRC.exists():
        sys.exit(f'缺少 {SRC.relative_to(ROOT)}，先跑 python3 scripts/fetch_roads.py')
    if not DIST.exists():
        sys.exit('先跑 python3 scripts/prep_districts.py 產生 data/tc_districts.json')
    districts = json.loads(DIST.read_text(encoding='utf-8'))['districts']
    rings = [r for d in districts for r in d['rings']]
    geo = json.loads(SRC.read_text(encoding='utf-8'))['data']

    # ── 每一段都要有交代：畫出來、裁掉、或者是不認識的等級 ────────────────
    out, dropped, unknown = [], 0, []
    pts_in = pts_out = 0
    for f in geo['features']:
        p = f['properties']
        cls = p.get('class')
        if cls not in KNOWN:
            unknown.append(cls)
            continue
        if f['geometry']['type'] != 'LineString':
            unknown.append(f['geometry']['type'])
            continue
        seg = f['geometry']['coordinates']
        pts_in += len(seg)
        kept = clip(seg, rings)
        if not kept:
            dropped += 1
            continue
        pts_out += sum(len(k) for k in kept)
        out.append({'cls': cls, 'num': p.get('num') or '', 'name': zh(p.get('name')),
                    'alias': zh(p.get('alias')), 'segs': kept})
    if unknown:
        sys.exit(f'來源檔出現不認識的等級或幾何型別：{sorted(set(unknown))}。'
                 f'CLASSES 只認得 {sorted(KNOWN)}，先確認來源改了什麼再說')
    if len(out) + dropped != len(geo['features']):
        sys.exit('分類加總不等於讀入筆數')
    if not out:
        sys.exit('裁切之後一段都不剩，市界或座標系統對不上，停下來')

    # ── 對帳：三個等級都必須留得下東西 ──────────────────────────────────
    # 全部被裁掉代表座標系統對不上，而不是臺中真的沒有國道
    by = collections.Counter(r['cls'] for r in out)
    missing = [c for c, _, _, _ in CLASSES if not by[c]]
    if missing:
        sys.exit(f'這些等級裁切後一段都不剩：{missing}。臺中三級公路都有，'
                 f'全沒了代表座標系統或市界對不上')

    # ── 對帳：抽稀不該把線抽到剩兩點 ────────────────────────────────────
    thin_out = [r for r in out if sum(len(s) for s in r['segs']) <= 2
                and sum(len(s) for s in r['segs']) < 2]
    if thin_out:
        sys.exit(f'{len(thin_out)} 段抽稀後只剩不到兩點，THIN 太大')

    src_by = collections.Counter(f['properties']['class'] for f in geo['features'])
    blob = {
        'city': '臺中市',
        'source': ('公路局路線圖資，經 yunching0513/taiwan-mobility-atlas 解析，'
                   '裁切至臺中市行政區界內'),
        'caveat': ('分級照來源檔的 class 欄位：國道、快速公路、省道。'
                   '市區道路不在這一份裡：公路局的公開圖資只到省道，'
                   '市區道路是市政府的權責，臺中市政府資料中心在本專案目前的網路環境連不到。'
                   '因此圖上看起來沒有路的地方不是沒有路，是那些路不在這份資料的範圍內。'
                   '第02節的公車路線疊圖是目前最接近市區道路的替代：'
                   '696條子路線走的就是市區的主要道路。'),
        'classes': [{'k': k, 'zh': label, 'color': c, 'w': w, 'n': by[k]}
                    for k, label, c, w in CLASSES],
        'counts': {'source': len(geo['features']), 'drawn': len(out), 'outsideCity': dropped,
                   'pointsIn': pts_in, 'pointsOut': pts_out},
        'roads': out,
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    print(f'{OUT.relative_to(ROOT)}：{len(out):,} 段、{OUT.stat().st_size / 1024:,.0f} KB')
    print(f'  來源 {len(geo["features"]):,} 段，裁切後市界內 {len(out):,}、全在市外 {dropped:,}')
    print(f'  點數 {pts_in:,} → {pts_out:,}（抽稀到 {pts_out / pts_in * 100:.1f}%）')
    for k, label, _, _ in CLASSES:
        print(f'  {label:6s} 來源 {src_by[k]:>5,} 段　市界內 {by[k]:>5,} 段')
    nums = collections.Counter(r['num'] for r in out)
    print('  路線編號：' + '、'.join(f'{n}（{c}段）' for n, c in nums.most_common(8)))


if __name__ == '__main__':
    main()
