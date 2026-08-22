#!/usr/bin/env python3
"""把臺中的村里人口與村里界線併成一份中間檔。

    python3 scripts/prep_villages.py

輸入在 data_TW/from_moi/（由 scripts/fetch_villages.py 抓下來）：

    village_pop.json          內政部戶政司 ODRP019，民國114年，全國逐村里
    village_geo_taichung.json g0v/twgeojson twVillage1982 的臺中593個里

輸出 data/tc_villages.json：畫得準的里逐個給多邊形，畫不準的區退回區級。

── 為什麼有些區只能畫到區級 ──────────────────────────────────────────
拿得到的界線是民國71年（1982）的版本。臺中現在有625個里，那份圖只有593個，
差在民國71年之後被再分割的里。這件事**不是均勻散布的**，它集中在幾個區：

    太平區 現有39個里，圖上只有19個多邊形
    潭子區 16／12　　大雅區 15／11　　大里區 27／25

被再分割意味著同名的那個舊多邊形，範圍比現在的同名里**大**。
把現在的人口填進那個舊多邊形，畫出來的密度會偏低，而且低得沒有規律。
**那不是缺一塊，那是畫錯。** 因此規則是：

    一個區的每一個里都對得到多邊形 → 這一區畫到里
    只要有一個對不到               → 整個區退回區級，並在版面上標明

寧可粗，不要錯。目前21個區畫到里、8個區畫到區級。
內政部的現行界線（dataset 7438，1150624版）取得之後，這8個區就能一起升級，
屆時只要換掉 data_TW/from_moi/village_geo_taichung.json 並重跑本程式。

── 異體字 ────────────────────────────────────────────────────────────
兩份來源用的字不一樣，逐一列在 VARIANT 裡，每一組都查證過是同一個里。
不列成通用規則而列成對照表，是因為「看起來像的字」與「同一個里」是兩件事，
前者可以自動判斷，後者不行。
"""
import collections
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'data_TW' / 'from_moi'
DIST = ROOT / 'data' / 'tc_districts.json'
OUT = ROOT / 'data' / 'tc_villages.json'

CITY = '臺中市'
EPS = 0.00035          # 道格拉斯普克容差，約 39 公尺
NDP = 5                # 座標小數位數，約 1 公尺
MIN_RING = 4           # 化簡後少於這麼多點的環丟掉，那是雜訊不是面

# 兩份來源寫法不同的里。左邊是戶政司、右邊是圖資，每一組都逐一核對過。
# 戶政司的「龜売里」用的是 U+2F85A（相容字），不是常見的 U+58F2。
VARIANT = {
    ('北屯區', '廍子里'): '部子里',
    ('外埔區', '廍子里'): '部子里',
    ('大肚區', '蔗廍里'): '蔗部里',
    ('大安區', '龜\U0002F85A里'): '龜殼里',   # U+2F85A，不是常見的 U+58F2
    ('清水區', '槺榔里'): '糠榔里',
    ('西區', '公舘里'): '公館里',
    ('西區', '双龍里'): '雙龍里',
}


def load(name, key='data'):
    p = SRC / name
    if not p.exists():
        sys.exit(f'缺少 {p.relative_to(ROOT)}，先跑 python3 scripts/fetch_villages.py')
    return json.loads(p.read_text(encoding='utf-8'))[key]


def pop(r):
    """三類戶的男女加總就是這個里的人口。"""
    return sum(int(r[f'household_{a}_{s}'])
               for a in ('ordinary', 'business', 'single') for s in ('m', 'f'))


def households(r):
    return sum(int(r[f'household_{a}_total'])
               for a in ('ordinary', 'business', 'single'))


def simplify(ring, eps):
    """道格拉斯普克。全國7,632個里的原始線形有35 MB，臺中這593個也有1.7 MB，
    單一檔 HTML 扛不動，而這張圖只有1120單位寬，39公尺遠小於一個像素。"""
    if len(ring) < 3:
        return ring
    stack, keep = [(0, len(ring) - 1)], {0, len(ring) - 1}
    while stack:
        a, b = stack.pop()
        ax, ay = ring[a]
        bx, by = ring[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        far, fd = -1, eps
        for i in range(a + 1, b):
            px, py = ring[i]
            d = (abs(dx * (ay - py) - (ax - px) * dy) / norm) if norm else math.hypot(px - ax, py - ay)
            if d > fd:
                far, fd = i, d
        if far > 0:
            keep.add(far)
            stack += [(a, far), (far, b)]
    return [ring[i] for i in sorted(keep)]


def rings_of(geom):
    """Polygon 與 MultiPolygon 一律攤成環的列表，只取外環。
    內環（洞）在村里界裡極少，而面量圖填色時洞會被相鄰的里蓋掉，不影響判讀。"""
    t, c = geom['type'], geom['coordinates']
    polys = [c] if t == 'Polygon' else c
    return [p[0] for p in polys if p and len(p[0]) >= MIN_RING]


def ring_area_km2(ring):
    """鞋帶公式，經度先乘 cos(緯度) 修正。只拿來排序與算密度。"""
    if len(ring) < 3:
        return 0.0
    kx = math.cos(sum(p[1] for p in ring) / len(ring) * math.pi / 180)
    a = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        a += (x1 * kx) * y2 - (x2 * kx) * y1
    return abs(a) / 2 * 111.32 * 111.32


def main():
    if not DIST.exists():
        sys.exit('先跑 python3 scripts/prep_districts.py 產生 data/tc_districts.json')
    districts = json.loads(DIST.read_text(encoding='utf-8'))['districts']
    dn = {d['name']: d for d in districts}

    rows = load('village_pop.json')
    geo = load('village_geo_taichung.json')['features']

    tc = [r for r in rows if r['site_id'].replace('台', '臺').startswith(CITY)]
    if not tc:
        sys.exit(f'戶政司的資料裡找不到{CITY}')
    year = tc[0]['statistic_yyy']

    # ── 圖資索引：(區, 里) → 環 ──────────────────────────────────────────
    poly = {}
    for f in geo:
        p = f['properties']
        poly[(p['TOWNNAME'].replace('台', '臺'), p['VILLAGENAM'])] = rings_of(f['geometry'])

    # ── 逐里配對，每一筆都要有交代 ──────────────────────────────────────
    matched, unmatched = [], []
    for r in tc:
        town = r['site_id'].replace('台', '臺')[len(CITY):]
        if town not in dn:
            sys.exit(f'戶政司的「{town}」不在本市29個區裡')
        name = r['village']
        key = (town, VARIANT.get((town, name), name))
        (matched if key in poly else unmatched).append((town, name, key, r))
    if len(matched) + len(unmatched) != len(tc):
        sys.exit('配對的加總不等於讀入筆數')

    # ── 對帳一：異體字對照表裡的每一組都必須真的用上 ──────────────────────
    # 沒用上代表來源改了寫法，那時候這張表就是誤導，該刪不該留
    used = {(t, n) for t, n, _, _ in matched if (t, n) in VARIANT}
    if used != set(VARIANT):
        sys.exit(f'異體字對照表有沒用上的：{sorted(set(VARIANT) - used)}，來源可能改了寫法')

    # ── 對帳二：一個多邊形不該對到兩個里 ────────────────────────────────
    dup = [k for k, c in collections.Counter(k for _, _, k, _ in matched).items() if c > 1]
    if dup:
        sys.exit(f'這些多邊形被兩個以上的里對到：{dup}')

    # ── 每一個區：全對到才畫到里，否則退回區級 ──────────────────────────
    miss_by = collections.Counter(t for t, _, _, _ in unmatched)
    fine = {d['name'] for d in districts if not miss_by[d['name']]}

    vills, coarse = [], []
    for town, name, key, r in matched:
        if town not in fine:
            continue
        rings = [simplify(rg, EPS) for rg in poly[key]]
        rings = [[[round(c, NDP) for c in p] for p in rg] for rg in rings if len(rg) >= MIN_RING]
        if not rings:
            sys.exit(f'{town}{name}化簡之後一個環都不剩，EPS 太大')
        area = sum(ring_area_km2(rg) for rg in rings)
        n = pop(r)
        vills.append({
            'name': name, 'district': town, 'rings': rings,
            'pop': n, 'households': households(r),
            'area': round(area, 3),
            'density': round(n / area) if area > 0.01 else None,
            'perHousehold': round(n / households(r), 2) if households(r) else None,
        })
    for d in districts:
        if d['name'] in fine:
            continue
        n = sum(pop(r) for t, _, _, r in matched + unmatched if t == d['name'])
        h = sum(households(r) for t, _, _, r in matched + unmatched if t == d['name'])
        # 面積用本檔的鞋帶公式算，不用官方公布的：圖上每一格的密度都要同一個基準，
        # 否則里與區級單元的顏色不能並排看
        ga = sum(ring_area_km2(r) for r in d['rings'])
        coarse.append({
            'name': d['name'], 'district': d['name'], 'rings': d['rings'],
            'pop': n, 'households': h, 'area': round(ga, 3),
            'density': round(n / ga) if ga else None,
            'perHousehold': round(n / h, 2) if h else None,
            'villages': len([1 for t, _, _, _ in matched + unmatched if t == d['name']]),
            'mapped': len([1 for t, _, _, _ in matched if t == d['name']]),
            'missPop': sum(pop(r) for t, _, _, r in unmatched if t == d['name']),
        })

    # ── 對帳三：畫出來的與退回區級的，人口加總必須等於全市 ────────────────
    total = sum(pop(r) for r in tc)
    drawn = sum(v['pop'] for v in vills) + sum(c['pop'] for c in coarse)
    if drawn != total:
        sys.exit(f'人口加總對不上：畫出來的 {drawn:,}、戶政司 {total:,}')

    # ── 對帳四：里的面積加總，必須貼近該區「用同一套算法」算出來的面積 ─────
    # 比的必須是同一個基準。tc_districts.json 的 area 是官方公布的面積，
    # 與界線幾何算出來的面積本來就不一樣，而且差得不小：
    # 梧棲區的幾何含臺中港的水域，比官方面積大一倍；東區則小了兩成七。
    # 拿官方面積去對里的幾何面積，抓到的是那個差，不是圖資對不上。
    # 因此兩邊都用本檔的鞋帶公式算，這樣才問得出「這兩份界線是不是同一個形狀」。
    #
    # 全市層級要很緊：兩份界線的全市面積必須幾乎相同（實測差 0.03%）。
    # 這一條抓的是「拿錯檔案」「投影不對」這種會讓整張圖失效的錯。
    #
    # 單一區則要放到一成，因為兩份界線的年代不同，內部的界線本來就會有出入：
    # 外埔區 +8.5% 對上后里區 −5.1%，兩個區相鄰、方向相反、全市不變，
    # 那是同一條界線在兩份檔案裡畫在不同地方，不是圖資壞掉。
    # 超過3%的一律記進 borderShift 帶到版面上：**放寬容差可以，安靜放寬不行。**
    va = sum(ring_area_km2(r) for f in geo for r in rings_of(f['geometry']))
    ga = sum(ring_area_km2(r) for d in districts for r in d['rings'])
    if abs(va - ga) / ga > 0.01:
        sys.exit(f'全市面積對不上：里界 {va:.1f} km²、區界 {ga:.1f} km²，'
                 f'差 {abs(va - ga) / ga * 100:.2f}%。兩份界線不是同一套座標或不是同一個範圍')
    shift = []
    for d in districts:
        g = sum(ring_area_km2(r) for r in d['rings'])
        a = sum(ring_area_km2(r) for f in geo
                if f['properties']['TOWNNAME'].replace('台', '臺') == d['name']
                for r in rings_of(f['geometry']))
        pc = (a - g) / g * 100
        if abs(pc) > 10:
            sys.exit(f'{d["name"]}的里面積加總 {a:.2f} 與區界幾何面積 {g:.2f} '
                     f'差 {pc:+.1f}%，超過一成就不是界線微調')
        if abs(pc) > 3:
            shift.append({'name': d['name'], 'villageKm2': round(a, 2),
                          'districtKm2': round(g, 2), 'pct': round(pc, 1)})

    fine_pop = sum(v['pop'] for v in vills)
    blob = {
        'city': CITY,
        'period': f'民國{year}年',
        'source': (f'人口與戶數：內政部戶政司開放資料 ODRP019，民國{year}年逐村里；'
                   f'界線：g0v/twgeojson twVillage1982。'
                   f'密度的分母是本檔用鞋帶公式從界線算出來的面積，不是官方公布的面積。'
                   f'兩者差得不小：梧棲區的界線幾何含臺中港的水域，比官方面積大一倍，'
                   f'東區則小了兩成七。圖上每一格的密度都用同一套算法，才能並排看'),
        'caveat': (f'拿得到的村里界線是民國71年版。臺中現有{len(tc)}個里，'
                   f'那份圖只有{len(poly)}個多邊形，差在民國71年之後被再分割的里。'
                   f'被再分割的里，同名的舊多邊形範圍比現在大，'
                   f'把現在的人口填進去畫出來的密度會偏低而且沒有規律，那不是缺一塊而是畫錯。'
                   f'因此規則是一個區的每一個里都對得到多邊形才畫到里，'
                   f'只要有一個對不到就整個區退回區級：'
                   f'{len(fine)}個區畫到里（{len(vills)}個里、'
                   f'{fine_pop / total * 100:.1f}%的人口），'
                   f'{len(coarse)}個區畫到區級（'
                   + '、'.join(f'{c["name"]}{c["mapped"]}／{c["villages"]}' for c in coarse)
                   + f'）。內政部的現行界線（dataset 7438）取得之後這{len(coarse)}個區就能一起升級。'
                   + (f'另有{len(shift)}個區的里界面積與區界面積差超過3%（'
                      + '、'.join(f'{r["name"]}{r["pct"]:+.1f}%' for r in shift)
                      + '），那是兩份界線的年代不同、同一條界線畫在不同地方，'
                        '全市面積只差0.03%，不影響整體。' if shift else '')),
        'counts': {'villages': len(tc), 'polygons': len(poly),
                   'drawnVillages': len(vills), 'fineDistricts': len(fine),
                   'coarseDistricts': len(coarse), 'unmatched': len(unmatched),
                   'population': total, 'finePopulation': fine_pop,
                   'households': sum(households(r) for r in tc)},
        'unmatched': sorted((t, n) for t, n, _, _ in unmatched),
        'borderShift': shift,
        'units': vills + coarse,
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    print(f'{OUT.relative_to(ROOT)}：{len(vills)} 個里 ＋ {len(coarse)} 個區級單元、'
          f'{OUT.stat().st_size / 1024:,.0f} KB')
    print(f'  戶政司 民國{year}年　{len(tc)} 個里、{total:,} 人、'
          f'{blob["counts"]["households"]:,} 戶')
    print(f'  圖資 {len(poly)} 個多邊形，對到 {len(matched)}、對不到 {len(unmatched)}')
    print(f'  畫到里的 {len(fine)} 區（{fine_pop:,} 人，{fine_pop / total * 100:.1f}%）')
    print(f'  退回區級的 {len(coarse)} 區：')
    for c in sorted(coarse, key=lambda c: -c['missPop']):
        print(f"    {c['name']:5s} {c['mapped']:2d}／{c['villages']:2d} 個里有多邊形，"
              f"對不到的那些住了 {c['missPop']:,} 人（占該區 {c['missPop'] / c['pop'] * 100:.1f}%）")
    if shift:
        print('  里界與區界面積差超過3%的區（兩份界線年代不同，全市只差 '
              f'{abs(va - ga) / ga * 100:.2f}%）：')
        for r in shift:
            print(f"    {r['name']:5s} 里界 {r['villageKm2']:7.2f}　"
                  f"區界 {r['districtKm2']:7.2f}　{r['pct']:+5.1f}%")
    top = sorted([v for v in vills if v['density']], key=lambda v: -v['density'])[:5]
    print('  人口密度最高的五個里：')
    for v in top:
        print(f"    {v['district']}{v['name']:5s} {v['density']:>7,} 人/km²　"
              f"（{v['pop']:>6,} 人、{v['area']:.3f} km²）")


if __name__ == '__main__':
    main()
