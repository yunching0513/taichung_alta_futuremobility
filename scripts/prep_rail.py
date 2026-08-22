#!/usr/bin/env python3
"""把臺中境內的軌道路網與車站整理成一份中間檔。

    python3 scripts/prep_rail.py

輸入在 data_TW/from_tdx_transit_twin/，來源寫在各檔的 _upstream 欄位：

    rail_network.json   軌道線形（GeoJSON），kind 分 tra／thsr／metro／lrt
    tra_stations.json   臺鐵車站座標，全臺245站

輸出 data/tc_rail.json：只留臺中市界內的線段與車站。

── 三件必須先講清楚的事 ────────────────────────────────────────────────
其一，**這份資料沒有臺中捷運綠線。** 來源檔的 metro 只有臺北捷運五線、桃園機場線，
與新北的淡海、安坑兩條輕軌，臺中捷運不在裡面。因此本檔的 systems 只會有臺鐵與高鐵。
綠線要另外取得，見 docs/sources.md。

其二，**這份資料沒有臺鐵的站等。** 臺鐵把車站分成特等、一等、二等、三等、簡易、招呼六級，
那是營運與人力配置的分級，來源檔只有站名與經緯度，沒有站等欄位。
本檔改用「這一站在哪一條線上」做分別：山線、海線、成追線，以及與高鐵轉乘的站。
這是從線形算出來的（門檻 200 公尺內的線全部列出，不是只取最近的一條，
所以追分與成功這兩個山海線交會站不會被算成只有一條線），可以驗證，唯它不是官方的站等。

其三，市界的裁切用的是行政區界的點在多邊形內判定，不是矩形。
矩形會把三義、彰化、花壇這些鄰縣的車站算進來，實際上它們不在臺中市。
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'data_TW' / 'from_tdx_transit_twin'
DIST = ROOT / 'data' / 'tc_districts.json'
OUT = ROOT / 'data' / 'tc_rail.json'

# 線形的抽稀門檻。來源檔的西部幹線全臺有 22,755 個點，臺中境內仍然過密，
# 畫在一張 1120 寬的圖上根本看不出差別，徒然把單一檔 HTML 撐大。
# 一個緯度約 111 公里，所以 0.00027 度大約是 30 公尺。
THIN = 0.00027

SYS_LABEL = {'tra': '臺鐵', 'thsr': '高鐵', 'metro': '捷運', 'lrt': '輕軌'}


def load(path):
    if not path.exists():
        sys.exit(f'缺少輸入檔：{path.relative_to(ROOT)}')
    return json.loads(path.read_text(encoding='utf-8'))


def inside(pt, rings):
    """射線法。點落在任何一個環內就算在區內（飛地也算）。"""
    x, y = pt
    hit = False
    for r in rings:
        n = len(r)
        for i in range(n):
            x1, y1 = r[i]
            x2, y2 = r[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                xx = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
                if x < xx:
                    hit = not hit
    return hit


def thin(line):
    """相鄰太近的點丟掉，端點一定留。"""
    if len(line) < 3:
        return line
    out = [line[0]]
    for p in line[1:-1]:
        q = out[-1]
        if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= THIN ** 2:
            out.append(p)
    out.append(line[-1])
    return out


def seg_dist(pt, a, b):
    """點到線段的距離，單位是度。只拿來比大小，不換算成公尺。"""
    px, py = pt
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def main():
    net = load(SRC / 'rail_network.json')
    sta = load(SRC / 'tra_stations.json')['stations']
    if not DIST.exists():
        sys.exit('先跑 python3 scripts/prep_districts.py 產生 data/tc_districts.json')
    districts = json.loads(DIST.read_text(encoding='utf-8'))['districts']
    rings = [r for d in districts for r in d['rings']]

    # ── 線形裁切：留下落在市界內的連續點列，兩端各多留一點讓線接到邊界 ──
    lines, dropped = [], []
    for f in net['features']:
        p = f['properties']
        kept = []
        for seg in f['geometry']['coordinates']:
            flags = [inside(pt, rings) for pt in seg]
            run = []
            for i, (pt, ok) in enumerate(zip(seg, flags)):
                if ok:
                    if not run and i > 0:
                        run.append(seg[i - 1])
                    run.append(pt)
                elif run:
                    run.append(pt)
                    if len(run) > 1:
                        kept.append(thin(run))
                    run = []
            if len(run) > 1:
                kept.append(thin(run))
        if kept:
            lines.append({
                'sys': p['sys'], 'kind': p['kind'], 'line': p['line'],
                'sysLabel': SYS_LABEL.get(p['kind'], p['kind']),
                'segments': kept,
                'points': sum(len(s) for s in kept),
            })
        else:
            dropped.append(p['line'])

    if not lines:
        sys.exit('裁切之後一條線都不剩，市界或座標系統對不上，停下來')

    # ── 車站：用行政區界判定，不用矩形 ──
    stops = []
    for sid, s in sta.items():
        pt = [s['lon'], s['lat']]
        home = next((d['name'] for d in districts if inside(pt, d['rings'])), None)
        if home is None:
            continue
        # 分別：門檻內的臺鐵線全部列出來，不是只取最近的一條。
        # 追分與成功是山海線的交會點，只取最近的一條會把交會這件事抹掉。
        # 門檻 0.0018 度約 200 公尺，足以涵蓋月台與路線中心線的偏差。
        near = []
        for L in lines:
            if L['kind'] != 'tra':
                continue
            dmin = min(seg_dist(pt, a, b)
                       for seg in L['segments'] for a, b in zip(seg, seg[1:]))
            near.append((dmin, L['line']))
        near.sort()
        best = near[0][1] if near else None
        allx = [n for d, n in near if d < 0.0018] or ([best] if best else [])
        # 高鐵線經過同一個點附近的，標成轉乘站
        hs = next((L for L in lines if L['kind'] == 'thsr'), None)
        near_hsr = False
        if hs:
            for seg in hs['segments']:
                for a, b in zip(seg, seg[1:]):
                    if seg_dist(pt, a, b) < 0.004:      # 約 400 公尺
                        near_hsr = True
                        break
                if near_hsr:
                    break
        stops.append({
            'id': sid, 'name': s['name'], 'lon': s['lon'], 'lat': s['lat'],
            'district': home, 'line': best, 'lines': allx,
            'junction': len(allx) > 1, 'hsrNear': near_hsr,
        })
    stops.sort(key=lambda t: -t['lat'])

    if not stops:
        sys.exit('臺中市界內一個車站都沒有，判定邏輯有問題，停下來')

    # ── 對帳：每一站都要落在某一個區裡，且都要分到一條線 ──
    for t in stops:
        if not t['district'] or not t['line']:
            sys.exit(f'{t["name"]} 站沒有分到行政區或路線：{t}')
    names = {d['name'] for d in districts}
    bad = [t['name'] for t in stops if t['district'] not in names]
    if bad:
        sys.exit(f'這些站分到了不存在的行政區：{bad}')

    by_line = {}
    for t in stops:
        for ln in t['lines']:
            by_line.setdefault(ln, []).append(t['name'])

    blob = {
        'city': '臺中市',
        'source': ('軌道線形與臺鐵車站座標取自 yunching0513/tdx-transit-twin 的 '
                   'data/static/，裁切至臺中市行政區界內'),
        'caveat': ('這份資料沒有臺中捷運綠線：來源檔的捷運只有臺北捷運、桃園機場線與'
                   '新北的兩條輕軌。也沒有臺鐵的站等（特等至招呼共六級），'
                   '本檔改用「這一站在哪一條線上」做分別，那是從線形算出來的，不是官方分級。'),
        'systems': sorted({L['sysLabel'] for L in lines}),
        'lines': lines,
        'stops': stops,
        'byLine': {k: len(v) for k, v in sorted(by_line.items())},
        'missing': ['臺中捷運綠線（線形與站點）', '臺鐵站等（特等／一等／二等／三等／簡易／招呼）',
                    '高鐵臺中站的站點座標（線形有，站點沒有）'],
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f'{OUT.relative_to(ROOT)}：{len(lines)} 條線、{len(stops)} 個車站')
    for L in lines:
        print(f"  {L['sysLabel']}　{L['line']:14s} 段 {len(L['segments'])}　點 {L['points']:,}")
    for k, v in sorted(by_line.items()):
        print(f'  {k}：{len(v)} 站　{"、".join(v)}')
    jx = [f"{t['name']}（{'＋'.join(t['lines'])}）" for t in stops if t['junction']]
    print(f'  交會站：{"、".join(jx) if jx else "無"}')
    hsr = [t['name'] for t in stops if t['hsrNear']]
    print(f'  與高鐵線相距 400 公尺內的臺鐵站：{"、".join(hsr) if hsr else "無"}')
    if dropped:
        print(f'  裁切後不進臺中而捨棄的線：{"、".join(dropped)}')


if __name__ == '__main__':
    main()
