#!/usr/bin/env python3
"""把臺中市公車的路線、班次與站牌整理成一份中間檔。

    python3 scripts/prep_bus.py

輸入（都在 data_TW/from_tdx/，由 scripts/fetch_tdx.py 抓下來）：

    bus_route_taichung.json      392 條路線的基本資料
    bus_shape_taichung.json      765 條子路線的線形（WKT）
    bus_schedule_taichung.json   696 條子路線的班表
    bus_stopofroute_taichung.json 每條子路線的完整停靠站序
    bus_stop_taichung.json       14,050 個站牌的座標

輸出 data/tc_bus.json：線形依班次密度畫粗細用的路線陣列，加上29個區的停靠班次。

── 為什麼是數班次，不是換算班距 ──────────────────────────────────────
TDX 的班表有兩種形態：696 條子路線裡，680 條給 Timetables（逐班的到站時刻），
16 條給 Frequencys（時段與最小、最大班距）。
**有時刻表就直接數班次，那是實數；只有班距的才用時段長度除以班距去估。**
兩者在輸出裡分別標成 counted 與 estimated，不混在一起當同一種東西看。

── 三個必須講清楚的定義 ──────────────────────────────────────────────
其一，時段是本檔自己定的，不是主計總處或電信信令的時段。
上午與下午刻意與信令那張圖對齊（07:00至13:00、13:00至19:00），
唯信令的「日間」與「夜間」是停留人口的彙總，公車沒有對應的東西，
因此本檔第四段用 19:00 至翌日 05:00 的夜間班次，並在版面上標明定義不同。

其二，時段一律按**發車時刻**歸段，區的停靠班次也是。
本來想按到站時刻歸段，唯班表的 StopTimes 只給起站那一筆
（11,516 班裡有 11,484 班如此），逐站的到站時刻拿不到。
因此區的停靠班次是這樣算的：**每條子路線在該區的站牌數 × 那條子路線的班次**。
這是一個推算，不是逐站點名，唯它推的是確定的事：
一班車跑完全程一定會停過它路線上的每一個站牌。
會失真的地方在時段：一班 06:30 從中臺科大發車的車，
停到終點站可能已經是 07:30，卻整趟都被算進上午那一段。
路線長的線受這個影響大，短的線小。

其三，同一班車若平日與假日都行駛，平日與假日各計一次。
這不是重複計算：兩個數字回答的是兩個不同的問題。

── 線形為什麼要抽稀 ──────────────────────────────────────────────────
原始線形 4.1 MB。整份頁面必須是單一檔案，不能靠 fetch，所以線形得瘦下來。
抽稀門檻 0.0012 度約 130 公尺：這張圖 1120 單位寬、跨約 0.6 度經度，
一個單位約 0.00054 度，所以門檻約 2.4 個像素。轉彎處會被切掉一點角，
唯這是一張全市尺度的班次密度圖，讀的是哪幾條走廊班次密集，不是導航用的。
門檻 0.0005 度（一個像素）會讓中間檔從 1.3 MB 變成 2.0 MB，不值得。
座標留四位小數（約11公尺），同理。
"""
import collections
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TDX = ROOT / 'data_TW' / 'from_tdx'
DIST = ROOT / 'data' / 'tc_districts.json'
OUT = ROOT / 'data' / 'tc_bus.json'

THIN = 0.0012      # 抽稀門檻，約130公尺、這張圖上約2.4個像素
NDP = 4            # 座標小數位數，約11公尺

# 時段。start 含、end 不含，單位是分鐘。夜間跨午夜，所以用「或」判定。
BANDS = [
    ('all', '全日', '每日全部班次', None),
    ('morning', '上午', '07:00–13:00', (7 * 60, 13 * 60)),
    ('afternoon', '下午', '13:00–19:00', (13 * 60, 19 * 60)),
    ('night', '夜間', '19:00–翌日05:00', (19 * 60, 5 * 60)),
]
DAYS = [('work', '平日'), ('weekend', '假日')]


def load(name):
    p = TDX / name
    if not p.exists():
        sys.exit(f'缺少 {p.relative_to(ROOT)}，先跑 python3 scripts/fetch_tdx.py')
    return json.loads(p.read_text(encoding='utf-8'))


def mins(hhmm):
    """'07:30' → 450。格式不對回 None，由呼叫端決定怎麼處理。"""
    try:
        h, m = hhmm.split(':')
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def band_of(t):
    """分鐘數落在哪些時段裡。all 一定算，其餘看區間。"""
    out = ['all']
    for k, _, _, rng in BANDS:
        if rng is None:
            continue
        a, b = rng
        if (a <= t < b) if a < b else (t >= a or t < b):
            out.append(k)
    return out


def days_of(sd):
    """ServiceDay → 這班車算平日、算假日，還是兩者都算。"""
    if not sd:
        return []
    out = []
    if any(sd.get(d) for d in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')):
        out.append('work')
    if sd.get('Saturday') or sd.get('Sunday'):
        out.append('weekend')
    return out


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


def wkt_line(s):
    if not s.upper().startswith('LINESTRING'):
        return None
    inner = s[s.index('(') + 1:s.rindex(')')]
    try:
        return [[float(a), float(b)] for a, b in (p.split() for p in inner.split(','))]
    except ValueError:
        return None


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


def zeros():
    return {d: {b: 0.0 for b, _, _, _ in BANDS} for d, _ in DAYS}


def main():
    if not DIST.exists():
        sys.exit('先跑 python3 scripts/prep_districts.py 產生 data/tc_districts.json')
    districts = json.loads(DIST.read_text(encoding='utf-8'))['districts']

    routes = load('bus_route_taichung.json')
    shapes = load('bus_shape_taichung.json')
    sched = load('bus_schedule_taichung.json')
    stops = load('bus_stop_taichung.json')
    sor = load('bus_stopofroute_taichung.json')

    # ── 站牌落區。TDX 的站牌沒有行政區欄位，只好用界線判定 ────────────────
    # 臺中的路線會開進南投、彰化、苗栗，那些站牌落不進任何一個區，
    # 不是錯誤而是事實，因此獨立計數而不是默默丟掉。
    stop_home, outside = {}, 0
    for s in stops:
        p = s.get('StopPosition') or {}
        pt = [p.get('PositionLon'), p.get('PositionLat')]
        if pt[0] is None or pt[1] is None:
            outside += 1
            continue
        home = next((d['name'] for d in districts if inside(pt, d['rings'])), None)
        if home is None:
            outside += 1
        else:
            stop_home[s['StopUID']] = home
    if not stop_home:
        sys.exit('一個站牌都沒有落進臺中的行政區，界線或座標對不上，停下來')

    # ── 班表：路線按發車時刻歸段、區按到站時刻歸段 ────────────────────────
    per_route = collections.defaultdict(zeros)
    per_route_kind = {}
    per_dist = {d['name']: zeros() for d in districts}
    trips_read = trips_used = 0
    bad_time = miss_stop = 0

    for r in sched:
        uid = r.get('SubRouteUID') or r.get('RouteUID')
        key = (uid, r.get('Direction'))
        tt = r.get('Timetables') or []
        fq = r.get('Frequencys') or []
        per_route_kind[key] = 'counted' if tt else ('estimated' if fq else None)

        for trip in tt:
            trips_read += 1
            st = trip.get('StopTimes') or []
            dd = days_of(trip.get('ServiceDay'))
            if not st or not dd:
                continue
            t0 = mins(st[0].get('DepartureTime') or st[0].get('ArrivalTime'))
            if t0 is None:
                bad_time += 1
                continue
            trips_used += 1
            for d in dd:
                for b in band_of(t0):
                    per_route[key][d][b] += 1

        for w in fq:
            a, b = mins(w.get('StartTime')), mins(w.get('EndTime'))
            hw = w.get('MaxHeadwayMins') or w.get('MinHeadwayMins')
            dd = days_of(w.get('ServiceDay'))
            if a is None or b is None or not hw or not dd:
                bad_time += 1
                continue
            span = (b - a) if b > a else (b + 1440 - a)
            n = span / hw
            trips_read += 1
            trips_used += 1
            # 班距是整段平均，所以把班次按分鐘攤平，再按分鐘歸段
            for d in dd:
                for m in range(a, a + span):
                    for bd in band_of(m % 1440):
                        per_route[key][d][bd] += n / span

    # ── 區的停靠班次：子路線在該區的站牌數 × 那條子路線的班次 ─────────────
    # 直接數到站時刻是算不出來的（StopTimes 只給起站），這是唯一可推的路。
    for r in sor:
        key = (r.get('SubRouteUID') or r.get('RouteUID'), r.get('Direction'))
        t = per_route.get(key)
        if t is None:
            continue                       # 有站序沒班表的子路線，下面的對帳會算進 no_sched
        here = collections.Counter()
        for st in r.get('Stops') or []:
            home = stop_home.get(st.get('StopUID'))
            if home is None:
                miss_stop += 1
                continue
            here[home] += 1
        for home, n in here.items():
            for d, _ in DAYS:
                for b, _, _, _ in BANDS:
                    per_dist[home][d][b] += t[d][b] * n
    if not any(v['work']['all'] for v in per_dist.values()):
        sys.exit('一個區都算不出停靠班次，站序與班表對不起來，停下來')

    # ── 線形接上班次 ─────────────────────────────────────────────────────
    name_of = {}
    for r in routes:
        for sr in r.get('SubRoutes') or []:
            name_of[sr['SubRouteUID']] = (r['RouteName']['Zh_tw'],
                                          sr.get('Headsign') or sr['SubRouteName']['Zh_tw'])
        name_of.setdefault(r['RouteUID'], (r['RouteName']['Zh_tw'], ''))

    out_routes, no_sched, no_geom = [], [], []
    for sh in shapes:
        uid = sh.get('SubRouteUID') or sh.get('RouteUID')
        key = (uid, sh.get('Direction'))
        pts = wkt_line(sh.get('Geometry') or '')
        if not pts or len(pts) < 2:
            no_geom.append(uid)
            continue
        if key not in per_route:
            no_sched.append(uid)
            continue
        nm, head = name_of.get(uid, (sh['RouteName']['Zh_tw'], ''))
        t = per_route[key]
        out_routes.append({
            'id': uid, 'dir': sh.get('Direction'), 'name': nm, 'headsign': head,
            'kind': per_route_kind.get(key),
            'trips': {d: {b: round(t[d][b], 1) for b, _, _, _ in BANDS} for d, _ in DAYS},
            'path': thin(pts),
        })
    if not out_routes:
        sys.exit('沒有一條路線同時有線形與班表，對不起來，停下來')

    # ── 對帳一：每一條線形都要有交代 ────────────────────────────────────
    if len(out_routes) + len(no_sched) + len(no_geom) != len(shapes):
        sys.exit('線形的分類加總不等於讀入筆數')

    # ── 對帳二：路線的班次加總必須等於區的停靠班次除以平均停靠站數的量級 ──
    # 這一條不是等式（一班車停很多站），改對「全日必須大於等於任一時段」這個必然關係
    for r in out_routes:
        for d, _ in DAYS:
            tot = r['trips'][d]['all']
            for b, _, _, rng in BANDS:
                if rng and r['trips'][d][b] > tot + 0.05:
                    sys.exit(f'{r["name"]} 的{d}{b}班次 {r["trips"][d][b]} 大於全日 {tot}')
    for n, v in per_dist.items():
        for d, _ in DAYS:
            if any(v[d][b] > v[d]['all'] + 0.05 for b, _, _, rng in BANDS if rng):
                sys.exit(f'{n} 的分時段停靠班次大於全日')

    # ── 對帳三：全市的停靠班次加總，必須等於逐條子路線各自算出來的加總 ────
    # 兩邊用不同的路徑算同一件事：一邊按區累加，一邊按子路線累加。
    lhs = sum(v['work']['all'] for v in per_dist.values())
    rhs = 0.0
    for r in sor:
        key = (r.get('SubRouteUID') or r.get('RouteUID'), r.get('Direction'))
        t = per_route.get(key)
        if t is None:
            continue
        rhs += t['work']['all'] * sum(1 for st in (r.get('Stops') or [])
                                      if st.get('StopUID') in stop_home)
    if abs(lhs - rhs) > 0.5:
        sys.exit(f'停靠班次兩種算法對不上：按區 {lhs:,.1f}、按子路線 {rhs:,.1f}')

    # ── 對帳四：每一個站牌都要有交代：落進某一區，或算進 outside ──────────
    if len(stop_home) + outside != len(stops):
        sys.exit('站牌的分類加總不等於讀入筆數')

    # ── 區級指標：每千位常住人口的每日停靠班次 ───────────────────────────
    res = {d['name']: d['residents'] for d in districts}
    cnt = collections.Counter(stop_home.values())
    rows = []
    for d in districts:
        n = d['name']
        v = per_dist[n]
        rows.append({
            'name': n, 'stops': cnt.get(n, 0),
            'stopsPerKm2': round(cnt.get(n, 0) / d['area'], 2) if d['area'] else None,
            'calls': {dd: {b: round(v[dd][b]) for b, _, _, _ in BANDS} for dd, _ in DAYS},
            'callsPerK': {dd: {b: round(v[dd][b] / res[n] * 1000, 1) if res[n] else None
                               for b, _, _, _ in BANDS} for dd, _ in DAYS},
            # 每平方公里的停靠班次。與每千人那個數的差別在分母：
            # 人口當分母時，人口少的區在「公車服務」與「死亡率」兩邊會同時偏高，
            # 兩者的相關係數因此會被共用的分母撐起來。面積當分母沒有這個問題。
            'callsPerKm2': {dd: {b: round(v[dd][b] / d['area'], 1) if d['area'] else None
                                 for b, _, _, _ in BANDS} for dd, _ in DAYS},
        })

    blob = {
        'city': '臺中市',
        'period': '民國115年8月',
        'source': ('交通部TDX：Bus/Route、Bus/Shape、Bus/Schedule、Bus/Stop 的 Taichung，'
                   f'路線{len(routes)}條、線形{len(shapes)}條、班表{len(sched)}條、'
                   f'站牌{len(stops):,}個'),
        'caveat': (f'{len(out_routes)}條子路線同時有線形與班表，畫得出來；'
                   f'{len(no_sched)}條有線形沒班表、{len(no_geom)}條線形讀不出來，兩者都沒有畫。'
                   f'班次是計畫班次，不是實際到站：塞車、脫班、臨時停駛都不在裡面。'
                   f'同一班車若平日與假日都行駛，平日與假日各計一次。'
                   f'{outside:,}個站牌不在臺中市界內（臺中的路線會開進南投、彰化與苗栗），'
                   f'區級的停靠班次不含它們。'
                   f'區的停靠班次是「子路線在該區的站牌數乘上那條子路線的班次」推算的，'
                   f'不是逐站點名：班表的 StopTimes 只給起站，逐站的到站時刻拿不到。'
                   f'因此一班車整趟都被歸進發車的那個時段，路線長的線受這個影響大。'),
        'bands': [{'k': k, 'zh': zh, 'when': w} for k, zh, w, _ in BANDS],
        'days': [{'k': k, 'zh': zh} for k, zh in DAYS],
        'counts': {'routes': len(routes), 'shapes': len(shapes), 'drawn': len(out_routes),
                   'noSchedule': len(no_sched), 'noGeometry': len(no_geom),
                   'stops': len(stops), 'stopsInCity': len(stop_home), 'stopsOutside': outside,
                   'tripsRead': trips_read, 'tripsUsed': trips_used,
                   'badTime': bad_time, 'missingStop': miss_stop,
                   'counted': sum(1 for r in out_routes if r['kind'] == 'counted'),
                   'estimated': sum(1 for r in out_routes if r['kind'] == 'estimated')},
        'routes': out_routes,
        'districts': rows,
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    kb = OUT.stat().st_size / 1024
    print(f'{OUT.relative_to(ROOT)}：{len(out_routes)} 條子路線、{kb:,.0f} KB')
    print(f'  線形 {len(shapes)}：畫了 {len(out_routes)}、'
          f'沒班表 {len(no_sched)}、線形讀不出來 {len(no_geom)}')
    print(f'  班次 讀入 {trips_read:,}　採用 {trips_used:,}　'
          f'時刻讀不出來 {bad_time}　（實數 {blob["counts"]["counted"]} 條、'
          f'班距估算 {blob["counts"]["estimated"]} 條）')
    print(f'  站牌 {len(stops):,}：市界內 {len(stop_home):,}、市界外 {outside:,}')
    print(f'  站序裡對不到站牌座標的 {miss_stop:,} 次')
    top = sorted(rows, key=lambda r: -r['calls']['work']['all'])[:5]
    print('  平日全日停靠班次最多的五個區：')
    for r in top:
        print(f"    {r['name']:5s} {r['calls']['work']['all']:>7,} 次　"
              f"站牌 {r['stops']:>4,}　每千人 {r['callsPerK']['work']['all']:>6.1f} 次")
    bot = sorted(rows, key=lambda r: r['callsPerK']['work']['all'])[:3]
    print('  每千人停靠班次最少的三個區：'
          + '、'.join(f"{r['name']}{r['callsPerK']['work']['all']:.1f}次" for r in bot))


if __name__ == '__main__':
    main()
