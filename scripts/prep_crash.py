#!/usr/bin/env python3
"""把臺中的A1死亡事故整理成一份中間檔。

    python3 scripts/prep_crash.py

輸入在 data_TW/from_mobility_atlas/，來源是 yunching0513/taiwan-mobility-atlas，
那個 repo 的上游是內政部警政署經 data.gov.tw 釋出的A1事故資料：

    taichung_a1_events.json   1,573件逐件資料，民國105至114年
    taichung_a1_yearly.json   同一份的年度彙總，拿來對帳
    taichung_agg.json         上游算好的區級十年彙總，也拿來對帳
    taichung_pop_102.json     區級人口（民國102年），上游算每萬人率用的分母

輸出 data/tc_crash.json：29個區的死亡數與運具別、逐件的熱點座標。

── A1 是什麼，不是什麼 ────────────────────────────────────────────────
A1 指「造成人員當場或24小時內死亡的交通事故」。它不是全部的交通事故：
A2（受傷）與A3（財損）都不在裡面。因此本頁的圖讀的是**死亡的分布**，
不是**危險的分布**，兩者不一樣：一條車速慢、車流大、天天擦撞的路可能一件A1都沒有。

── 三個不同的分母，不要混著讀 ────────────────────────────────────────
其一，**區級死亡數是十年完整的**：民國105至114年，1,573件、1,607人。
其二，**熱點座標從民國107年才有**。105與106兩年的212件沒有經緯度，
上游的年度彙總自己就寫 with_coords: 0。所以點位圖是八年，不是十年。
其三，**道路型態、速限、肇因這些欄位只有1,174件有**，其餘399件是簡表。
每一張圖各自標自己的件數，不共用一個「1,573」。

── 為什麼率要帶區間 ──────────────────────────────────────────────────
石岡區十年只有7人死亡，和平區16人。除以人口得到的「每十萬人」看起來像一個數字，
其實它的不確定性很大：**7這個數如果換一個十年，很可能是4，也很可能是11。**
因此本檔的每十萬人一律附上以卜瓦松近似算出的95%區間（率 ± 1.96√死亡數 / 人口），
死亡數低於10的另外標成 small，提醒不要拿它跟大區的數字並排排名。
給一個看起來像數字的雜訊，比留白更糟。

── 運具的定義 ────────────────────────────────────────────────────────
上游以**最脆弱用路人**分類（行人 > 慢車 > 機車 > 汽貨車），不是以肇事的主要當事者。
一輛左轉小客車撞死行人，主要當事者是駕駛、運具是汽車，這裡歸類為「人」。
這個選擇會改變數字的意義：它問的是「誰死了」，不是「誰肇事」。
"""
import collections
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'data_TW' / 'from_mobility_atlas'
DIST = ROOT / 'data' / 'tc_districts.json'
OUT = ROOT / 'data' / 'tc_crash.json'

FIRST_COORD_YEAR = 2018      # 民國107年。這一年之前上游沒有經緯度
NDP = 5                      # 熱點座標小數位數，約1公尺
SMALL_N = 10                 # 死亡數低於這個值，率就標成 small，不進排名
MODES = ['人', '機車', '汽車', '慢車', '其他']

# 熱點圖要帶的欄位。parties 與 vehicles_raw 太細也太大，留在原始檔裡就好
KEEP = ['year', 'date', 'time', 'location', 'district', 'deaths', 'mode',
        'road_type', 'speed_limit', 'road_shape_main', 'signal', 'light', 'cause_main']


def load(name):
    p = SRC / name
    if not p.exists():
        sys.exit(f'缺少 {p.relative_to(ROOT)}')
    return json.loads(p.read_text(encoding='utf-8'))['data']


def has_xy(r):
    return (isinstance(r.get('lon'), (int, float)) and abs(r['lon']) > 100
            and isinstance(r.get('lat'), (int, float)) and abs(r['lat']) > 10)


def main():
    if not DIST.exists():
        sys.exit('先跑 python3 scripts/prep_districts.py 產生 data/tc_districts.json')
    districts = json.loads(DIST.read_text(encoding='utf-8'))['districts']
    names = [d['name'] for d in districts]
    res = {d['name']: d['residents'] for d in districts}

    ev = load('taichung_a1_events.json')
    yearly = load('taichung_a1_yearly.json')
    agg = load('taichung_agg.json')

    # ── 每一筆都要有交代：納入，或某一個具名的排除原因 ────────────────────
    kept, no_district, no_coord = [], 0, 0
    per = {n: {'deaths': 0, 'events': 0, 'byMode': dict.fromkeys(MODES, 0),
               'byYear': {}} for n in names}
    years = set()
    for r in ev:
        d = r.get('district')
        if d not in per:
            no_district += 1          # 區名對不上，寧可算進排除也不硬塞
            continue
        y = r.get('year')
        years.add(y)
        per[d]['events'] += 1
        per[d]['deaths'] += r.get('deaths') or 0
        m = r.get('mode') if r.get('mode') in MODES else '其他'
        per[d]['byMode'][m] += 1
        per[d]['byYear'][str(y)] = per[d]['byYear'].get(str(y), 0) + 1
        if has_xy(r):
            row = {k: r.get(k) for k in KEEP if r.get(k) not in (None, '')}
            row['lon'] = round(r['lon'], NDP)
            row['lat'] = round(r['lat'], NDP)
            kept.append(row)
        else:
            no_coord += 1
    if len(kept) + no_coord + no_district != len(ev):
        sys.exit('逐件資料的分類加總不等於讀入筆數')
    if not kept:
        sys.exit('一件都沒有座標，熱點圖畫不出來，停下來')

    # ── 對帳一：逐件加總必須等於上游的年度彙總 ───────────────────────────
    ye = collections.Counter(r['year'] for r in ev)
    yd = collections.Counter()
    for r in ev:
        yd[r['year']] += r.get('deaths') or 0
    for row in yearly:
        y = row['year']
        if ye[y] != row['events']:
            sys.exit(f'{y}年件數對不上：逐件 {ye[y]}、上游彙總 {row["events"]}')
        if yd[y] != row['deaths']:
            sys.exit(f'{y}年死亡數對不上：逐件 {yd[y]}、上游彙總 {row["deaths"]}')

    # ── 對帳二：區級加總必須等於上游 agg.json 的區級數字 ──────────────────
    up = {r['district']: r for r in agg}
    for n in names:
        u = up.get(n)
        if u is None:
            sys.exit(f'上游的 agg.json 裡沒有 {n}')
        if per[n]['deaths'] != u['deaths'] or per[n]['events'] != u['events']:
            sys.exit(f'{n} 對不上：本檔 {per[n]["deaths"]}死/{per[n]["events"]}件、'
                     f'上游 {u["deaths"]}死/{u["events"]}件')
    if len(up) != len(names):
        sys.exit(f'上游有 {len(up)} 個區，本市有 {len(names)} 個，對不上')

    # ── 對帳三：座標的有無必須完全依年份切開，不是隨機缺漏 ────────────────
    # 若某一年半有半沒有，那就不是「這一年之前沒有座標」而是資料品質問題，
    # 那會讓「民國107年起」這句話變成錯的。
    for y in sorted(years):
        n = ye[y]
        c = sum(1 for r in ev if r['year'] == y and has_xy(r))
        if c not in (0, n):
            sys.exit(f'{y}年 {n} 件裡只有 {c} 件有座標，座標的有無不是按年切開的，'
                     f'「民國{y - 1911}年起才有座標」這句話不能寫')
        if (c == n) != (y >= FIRST_COORD_YEAR):
            sys.exit(f'{y}年的座標有無與 FIRST_COORD_YEAR={FIRST_COORD_YEAR} 不一致')

    # ── 區級指標。每十萬人用本 repo 的常住人口，不用上游民國102年的人口 ────
    # 理由：這一頁其他所有的區級率都用同一個分母（普查的常住人口），
    # 混用兩套人口會讓同一頁上的兩個「每十萬人」不能互相比較。
    rows = []
    for d in districts:
        n = d['name']
        p = per[n]
        rows.append({
            'name': n, 'deaths': p['deaths'], 'events': p['events'],
            'byMode': p['byMode'], 'byYear': p['byYear'],
            'per100k': round(p['deaths'] / res[n] * 1e5, 1) if res[n] else None,
            # 卜瓦松近似的95%區間。死亡數少的區，這個區間會寬到讓排名失去意義
            'per100kLo': round(max(0, p['deaths'] - 1.96 * math.sqrt(p['deaths']))
                               / res[n] * 1e5, 1) if res[n] else None,
            'per100kHi': round((p['deaths'] + 1.96 * math.sqrt(p['deaths']))
                               / res[n] * 1e5, 1) if res[n] else None,
            'small': p['deaths'] < SMALL_N,
            'motoShare': round(p['byMode']['機車'] / p['events'] * 100, 1) if p['events'] else None,
            'pedShare': round(p['byMode']['人'] / p['events'] * 100, 1) if p['events'] else None,
        })

    tot_d = sum(r['deaths'] for r in rows)
    tot_e = sum(r['events'] for r in rows)
    mode_tot = {m: sum(r['byMode'][m] for r in rows) for m in MODES}
    yrs = sorted(years)

    blob = {
        'city': '臺中市',
        'period': f'民國{yrs[0] - 1911}至{yrs[-1] - 1911}年',
        'coordPeriod': f'民國{FIRST_COORD_YEAR - 1911}至{yrs[-1] - 1911}年',
        'source': ('內政部警政署A1事故資料，經 data.gov.tw 釋出，'
                   '由 yunching0513/taiwan-mobility-atlas 解析；'
                   '每十萬人的分母改用本 repo 的普查常住人口，'
                   '與本頁其他區級比率同一套'),
        'caveat': (f'A1 指人員當場或24小時內死亡的事故，不含A2受傷與A3財損，'
                   f'因此這是死亡的分布，不是危險的分布。'
                   f'區級死亡數十年完整（{tot_e:,}件、{tot_d:,}人），'
                   f'唯熱點座標從民國{FIRST_COORD_YEAR - 1911}年才有：'
                   f'民國{yrs[0] - 1911}與{yrs[0] - 1910}兩年共{no_coord}件沒有經緯度，'
                   f'點位圖是{yrs[-1] - FIRST_COORD_YEAR + 1}年不是{len(yrs)}年。'
                   f'運具以最脆弱用路人分類（行人優先於慢車、機車、汽貨車），'
                   f'問的是誰死了，不是誰肇事。'
                   f'每十萬人附95%區間（卜瓦松近似）：石岡區十年只有7人，'
                   f'那個率的區間寬到不該拿去排名，因此另外標成 small。'),
        'totals': {'deaths': tot_d, 'events': tot_e, 'byMode': mode_tot,
                   'years': len(yrs), 'perYear': round(tot_d / len(yrs), 1),
                   'points': len(kept), 'noCoord': no_coord, 'noDistrict': no_district,
                   # 有座標與有詳細欄位是兩個不同的件數，不可以互相代用
                   'detailed': sum(1 for r in ev if r.get('road_type') and r.get('speed_limit')),
                   'withSpeed': sum(1 for r in ev if r.get('speed_limit'))},
        'modes': MODES,
        'byYear': {str(y): {'events': ye[y], 'deaths': yd[y]} for y in yrs},
        'districts': rows,
        'points': kept,
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    print(f'{OUT.relative_to(ROOT)}：{tot_e:,} 件、{tot_d:,} 人、'
          f'{OUT.stat().st_size / 1024:,.0f} KB')
    print(f'  期間 {blob["period"]}　平均每年 {blob["totals"]["perYear"]} 人')
    print(f'  運具：' + '、'.join(f'{m}{mode_tot[m]:,}（{mode_tot[m] / tot_e * 100:.1f}%）'
                                 for m in MODES if mode_tot[m]))
    print(f'  熱點座標 {len(kept):,} 件（{blob["coordPeriod"]}）、'
          f'無座標 {no_coord} 件、區名對不上 {no_district} 件')
    print(f'  帶道路型態與速限的 {blob["totals"]["detailed"]:,} 件'
          f'（{blob["totals"]["detailed"] / tot_e * 100:.1f}%），其餘是簡表')
    print(f'  死亡數低於{SMALL_N}人、率標成 small 的區：'
          + ('、'.join(r['name'] for r in rows if r['small']) or '無'))
    top = sorted(rows, key=lambda r: -r['per100k'])[:5]
    print('  每十萬人死亡最高的五個區（括號是95%區間）：')
    for r in top:
        print(f"    {r['name']:5s} {r['per100k']:6.1f} 人　"
              f"（{r['per100kLo']:.1f}–{r['per100kHi']:.1f}，十年{r['deaths']:3d}人，"
              f"機車占{r['motoShare']:.0f}%、行人占{r['pedShare']:.0f}%）"
              + ('　樣本少' if r['small'] else ''))
    low = sorted(rows, key=lambda r: r['per100k'])[:3]
    print('  最低的三個區：' + '、'.join(f"{r['name']}{r['per100k']:.1f}人" for r in low))


if __name__ == '__main__':
    main()
