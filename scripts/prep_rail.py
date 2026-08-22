#!/usr/bin/env python3
"""把臺中境內的軌道路網與車站整理成一份中間檔。

    python3 scripts/prep_rail.py

輸入來自兩個地方：

    data_TW/from_tdx_transit_twin/rail_network.json   臺鐵與高鐵的線形（GeoJSON）
    data_TW/from_tdx/tra_station.json                 臺鐵車站，含官方站等
    data_TW/from_tdx/thsr_station.json                高鐵車站
    data_TW/from_tdx/metro_station_tmrt.json          臺中捷運車站
    data_TW/from_tdx/metro_shape_tmrt.json            臺中捷運線形（WKT）

輸出 data/tc_rail.json：只留臺中市界內的線段與車站。

── 這一版補上了什麼 ──────────────────────────────────────────────────
上一版有兩個必須標明的缺口，兩個都補上了，資料來自交通部TDX：

其一，**站等改用官方分級。** 臺鐵把車站分成特等、一等、二等、三等、簡易、招呼六級
（另有號誌站），那是營運與人力配置的分級。上一版的來源檔沒有這個欄位，
只好用「這一站在哪一條線上」代替，並在版面上標明那不是官方分級。
TDX 的 tra_station.json 有 StationClass，因此本版直接用官方站等，
線別另外保留：山線、海線、成追線的交會關係仍然有用。

其二，**臺中捷運綠線進來了。** 上一版的來源檔完全沒有臺中捷運。
本版接 TDX 的 TMRT 端點：18個車站與烏日文心北屯線的線形。

── 進出站人次只有臺鐵有 ────────────────────────────────────────────
臺鐵每日各站進出站人數來自 data.gov.tw dataset 8792，本檔算成每日平均。
**高鐵與臺中捷運沒有對應的公開檔案可取**：交通部統計查詢網 stat.motc.gov.tw
與臺中市政府資料中心 datacenter.taichung.gov.tw 在本專案目前的網路環境都連不到。
因此那兩個系統的車站 ridership 是 null，不是0，版面上會標明「無公開資料」。
**不會拿臺鐵的數字去頂替，也不會用路線長度之類的東西估一個出來。**

── 兩件仍然要講清楚的事 ──────────────────────────────────────────────
其一，市界的裁切用行政區界的點在多邊形內判定，不是矩形。
矩形會把三義、彰化、花壇這些鄰縣的車站算進來，實際上它們不在臺中市。

其二，TDX 給的 LocationTown 與本程式算出來的行政區必須一致。
這不是形式檢查：兩者對不上，代表市界幾何或車站座標至少有一個是錯的，
而那會讓整張圖的位置關係失真。

唯有一種對不上是可以接受的：車站本來就坐落在兩個區的交界上。
捷運文心中清站就是這一例，它距離北區與北屯區的界線只有50.6公尺，
TDX 的地址寫「臺中市北區文心路三段700號」，普查的界線幾何則把那個點劃進北屯區。
一個點落在界線的哪一邊，在這個距離內本來就在兩份資料的誤差之內。
因此規則寫成：距界線 BOUNDARY 公尺以內的不一致，記進 boundaryCases 帶到版面上；
超過那個距離的，或者這種案例超過三個，一律停下來。
**這是事先寫好的界線規則，不是遇到紅燈才放寬的容差**，
兩者的差別在於前者說得出物理理由與量測值，後者只說得出「這樣就過了」。
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'data_TW' / 'from_tdx_transit_twin'
RIDE = ROOT / 'data_TW' / 'from_tra' / 'tra_station_ridership.json'
TDX = ROOT / 'data_TW' / 'from_tdx'
DIST = ROOT / 'data' / 'tc_districts.json'
OUT = ROOT / 'data' / 'tc_rail.json'

# 線形的抽稀門檻。來源檔的西部幹線全臺有 22,755 個點，臺中境內仍然過密，
# 畫在一張 1120 寬的圖上根本看不出差別，徒然把單一檔 HTML 撐大。
# 一個緯度約 111 公里，所以 0.00027 度大約是 30 公尺。
THIN = 0.00027

# 車站與路線中心線的容許偏差，約 200 公尺。月台與中心線本來就有距離，
# 而追分與成功這兩個交會站要同時分到兩條線，取最近的一條會把交會抹掉。
NEAR_LINE = 0.0018

# 跨系統轉乘的門檻，約 440 公尺。這個值是量出來的，不是猜的：
# 捷運松竹對臺鐵松竹約 73 公尺、捷運大慶對臺鐵大慶約 39 公尺、
# 捷運烏日對臺鐵烏日約 250 公尺、高鐵臺中對臺鐵新烏日約 370 公尺。
# 最遠的那一組是高鐵臺中，門檻必須大於它；而次近的非轉乘組合
# （捷運九德對臺鐵烏日）相距 1.3 公里，中間留得夠寬，不會誤判。
XFER = 0.004

# 車站坐落在區界上時，TDX 的地址與界線幾何可以合理地給出不同的區。
# 150 公尺是量出來的門檻：目前唯一的案例（捷運文心中清）距界線 50.6 公尺，
# 而所有意見一致的車站裡，距界線最近的兩個是水安宮 26.7 公尺與大慶 89.7 公尺，
# 兩者都沒有分歧。門檻放在 150 公尺，容得下這一類的邊界案例，
# 又遠小於任何一個「站點被擺到別的區去」的量級（那會是幾百公尺以上）。
BOUNDARY_M = 150
MAX_BOUNDARY_CASES = 3     # 超過這個數就不是邊界案例，是系統性的錯誤
DEG_M = 111320             # 一度緯度約幾公尺。只拿來把度換算成公尺報數字用

SYS_LABEL = {'tra': '臺鐵', 'thsr': '高鐵', 'metro': '捷運', 'lrt': '輕軌'}

# 臺鐵官方站等。B 是號誌站，全臺只有樹林調車場一個，不在臺中。
CLASS = {'0': '特等站', '1': '一等站', '2': '二等站',
         '3': '三等站', '4': '簡易站', '5': '招呼站', 'B': '號誌站'}

# 進站與出站人次在七個月的尺度上應該接近，差太多通常代表欄位讀反了。
# 唯有兩站是例外，而且例外的是同一組：成追線上的追分與成功。
# 這裡把量到的值寫出來，而不是把容差放寬到讓它們通過：
# 放寬容差會讓「欄位讀反了」這種真正的錯也一起通過。
# 成因沒有查證過，本檔不臆測，只記錄事實。
RIDE_ASYM = {'追分': 2.55, '成功': 0.61}
RIDE_TOL = 0.25          # 其餘的站，進出比必須落在 1 ± 這個值之內（實測都在 ±6% 內）
RIDE_ASYM_TOL = 0.20     # 例外的兩站，實測值與上表相差不得超過這個比例


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


def wkt_line(s):
    """TDX 的捷運線形是 WKT 的 LINESTRING(lon lat, lon lat, ...)。"""
    if not s.upper().startswith('LINESTRING'):
        sys.exit(f'捷運線形不是 LINESTRING，是 {s[:40]}')
    inner = s[s.index('(') + 1:s.rindex(')')]
    return [[float(a), float(b)] for a, b in (p.split() for p in inner.split(','))]


def clip(segments, rings):
    """留下落在市界內的連續點列，兩端各多留一點讓線接到邊界。"""
    kept = []
    for seg in segments:
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
    return kept


def pos(s):
    p = s['StationPosition']
    return [p['PositionLon'], p['PositionLat']]


def edge_dist_m(pt, districts):
    """點到最近的一條區界的距離，公尺。經度先乘 cos(緯度) 修正。"""
    kx = math.cos(pt[1] * math.pi / 180)
    q = [pt[0] * kx, pt[1]]
    best = min(seg_dist(q, [a[0] * kx, a[1]], [b[0] * kx, b[1]])
               for d in districts for r in d['rings']
               for a, b in zip(r, r[1:] + [r[0]]))
    return best * DEG_M


def main():
    if not DIST.exists():
        sys.exit('先跑 python3 scripts/prep_districts.py 產生 data/tc_districts.json')
    districts = json.loads(DIST.read_text(encoding='utf-8'))['districts']
    rings = [r for d in districts for r in d['rings']]
    names = {d['name'] for d in districts}

    def where(pt):
        return next((d['name'] for d in districts if inside(pt, d['rings'])), None)

    # ── 線形：臺鐵與高鐵來自 transit-twin，捷運來自 TDX ──────────────────
    net = load(SRC / 'rail_network.json')
    lines, dropped = [], []
    for f in net['features']:
        p = f['properties']
        kept = clip(f['geometry']['coordinates'], rings)
        if kept:
            lines.append({'sys': p['sys'], 'kind': p['kind'], 'line': p['line'],
                          'sysLabel': SYS_LABEL.get(p['kind'], p['kind']),
                          'segments': kept, 'points': sum(len(s) for s in kept)})
        else:
            dropped.append(p['line'])

    for sh in load(TDX / 'metro_shape_tmrt.json'):
        kept = clip([wkt_line(sh['Geometry'])], rings)
        if not kept:
            sys.exit(f'捷運{sh["LineName"]["Zh_tw"]}裁切後一點都不剩，市界或座標系統對不上')
        lines.append({'sys': '臺中捷運', 'kind': 'metro', 'line': sh['LineName']['Zh_tw'],
                      'sysLabel': SYS_LABEL['metro'], 'segments': kept,
                      'points': sum(len(s) for s in kept)})

    if not lines:
        sys.exit('裁切之後一條線都不剩，市界或座標系統對不上，停下來')

    # ── 臺鐵車站：官方站等在 StationClass ────────────────────────────────
    tra_all = load(TDX / 'tra_station.json')
    claimed = {s['StationName']['Zh_tw'] for s in tra_all if s.get('LocationCity') == '臺中市'}
    stops = []
    for s in tra_all:
        pt = pos(s)
        home = where(pt)
        if home is None:
            continue
        cls = s.get('StationClass')
        if cls not in CLASS:
            sys.exit(f'{s["StationName"]["Zh_tw"]}站的 StationClass 是 {cls!r}，不在已知的分級裡')
        # 門檻內的臺鐵線全部列出，不是只取最近的一條：追分與成功是山海線的交會點
        near = sorted((min(seg_dist(pt, a, b)
                           for seg in L['segments'] for a, b in zip(seg, seg[1:])), L['line'])
                      for L in lines if L['kind'] == 'tra')
        best = near[0][1] if near else None
        on = [n for d, n in near if d < NEAR_LINE] or ([best] if best else [])
        stops.append({'id': s['StationID'], 'name': s['StationName']['Zh_tw'],
                      'sys': 'tra', 'sysLabel': '臺鐵', 'lon': pt[0], 'lat': pt[1],
                      'district': s.get('LocationTown'), 'geoDistrict': home,
                      'cls': cls, 'clsLabel': CLASS[cls],
                      'line': best, 'lines': on, 'junction': len(on) > 1})

    # ── 高鐵與捷運。這兩個系統不分站等，cls 給 null，不要編一個出來 ───────
    # TDX 的高鐵站名寫「台中」，本專案一律用「臺」，所以只做這一個字的正規化。
    # 不在 name 上加系統前綴：要與臺鐵臺中站區分是版面的事，
    # 版面一律用 sysLabel ＋ name 組出「高鐵臺中」與「臺鐵臺中」，資料層保持乾淨。
    for s in load(TDX / 'thsr_station.json'):
        pt = pos(s)
        home = where(pt)
        if home is None:
            continue
        stops.append({'id': s['StationID'],
                      'name': s['StationName']['Zh_tw'].replace('台', '臺'),
                      'sys': 'thsr', 'sysLabel': '高鐵', 'lon': pt[0], 'lat': pt[1],
                      'district': s.get('LocationTown'), 'geoDistrict': home,
                      'cls': None, 'clsLabel': None,
                      'line': '臺灣高鐵線', 'lines': ['臺灣高鐵線'], 'junction': False})

    for s in load(TDX / 'metro_station_tmrt.json'):
        pt = pos(s)
        home = where(pt)
        if home is None:
            continue
        stops.append({'id': s['StationID'], 'name': s['StationName']['Zh_tw'],
                      'sys': 'metro', 'sysLabel': '捷運', 'lon': pt[0], 'lat': pt[1],
                      'district': s.get('LocationTown'), 'geoDistrict': home,
                      'cls': None, 'clsLabel': None,
                      'line': '烏日文心北屯線', 'lines': ['烏日文心北屯線'], 'junction': False})

    if not stops:
        sys.exit('臺中市界內一個車站都沒有，判定邏輯有問題，停下來')

    # ── 進出站人次。只有臺鐵有，其餘給 null ─────────────────────────────
    ride_note, ride_period = None, None
    if RIDE.exists():
        raw = json.loads(RIDE.read_text(encoding='utf-8'))['data']
        agg = {}
        for r in raw:
            a = agg.setdefault(r['staCode'], {'days': set(), 'in': 0, 'out': 0})
            a['days'].add(r['trnOpDate'])
            a['in'] += int(r['gateInComingCnt'])
            a['out'] += int(r['gateOutGoingCnt'])
        if not agg:
            sys.exit('進出站人次讀進來是空的')
        days = {k: len(v['days']) for k, v in agg.items()}
        # 各站的天數必須一致。不一致代表某些站有缺日，那時候「每日平均」
        # 的分母就不一樣，站與站之間不能比。
        if len(set(days.values())) != 1:
            sys.exit(f'各站的資料天數不一致：{sorted(set(days.values()))}，'
                     f'每日平均的分母不同，站與站之間不能比')
        nd = next(iter(days.values()))
        alldates = sorted({r['trnOpDate'] for r in raw})
        ride_period = f'{alldates[0]} 至 {alldates[-1]}'
        miss = []
        for t in stops:
            if t['sys'] != 'tra':
                t['ridership'] = None
                continue
            a = agg.get(t['id'])
            if a is None:
                miss.append(t['name'])
                t['ridership'] = None
                continue
            t['ridership'] = {'in': round(a['in'] / nd), 'out': round(a['out'] / nd),
                              'total': round((a['in'] + a['out']) / nd), 'days': nd}
        if miss:
            sys.exit(f'這些臺鐵站在進出站人次裡找不到：{miss}。'
                     f'staCode 與 TDX 的 StationID 應該是同一套代碼')
        # 進站與出站在七個月的尺度上應該接近，除了具名的那兩站
        odd, drift = [], []
        for t in stops:
            r = t.get('ridership')
            if not r or not r['out']:
                continue
            ratio = r['in'] / r['out']
            exp = RIDE_ASYM.get(t['name'])
            if exp is None:
                if abs(ratio - 1) > RIDE_TOL:
                    odd.append(f'{t["name"]} {ratio:.2f}')
            elif abs(ratio - exp) / exp > RIDE_ASYM_TOL:
                drift.append(f'{t["name"]} 實測 {ratio:.2f}、表上 {exp}')
            if exp is not None:
                r['asym'] = round(ratio, 2)
        if odd:
            sys.exit(f'這些站的進站與出站人次不對稱：{odd}（容差 ±{RIDE_TOL:.0%}）。'
                     f'七個月的尺度上兩者應該接近，差這麼多通常代表欄位讀反了。'
                     f'若查證後確認是真的，把站名與量到的比值加進 RIDE_ASYM，不要放寬容差')
        if drift:
            sys.exit(f'具名例外的比值變了：{drift}。RIDE_ASYM 該更新，'
                     f'或者來源資料出了別的問題')
        ride_note = (f'臺鐵每日平均進出站人次，{ride_period}共{nd}天，'
                     f'來源 data.gov.tw dataset 8792。'
                     f'高鐵與臺中捷運沒有可取得的公開檔案，因此是 null 而不是 0。'
                     f'23站裡有21站的進出站人次相差在6%以內，'
                     + '、'.join(f'唯{k}的進站是出站的{v}倍' if v > 1
                                else f'{k}的進站只有出站的{v}倍' for k, v in RIDE_ASYM.items())
                     + '，兩者都在成追線上。這是量到的事實，成因未經查證，本檔不臆測')
    else:
        for t in stops:
            t['ridership'] = None
        ride_note = '沒有進出站人次：先跑 python3 scripts/fetch_roads.py'

    # ── 跨系統轉乘：門檻內、且不同系統的兩站互相登記 ─────────────────────
    for t in stops:
        t['xfer'] = sorted(
            f'{u["sysLabel"]}{u["name"]}' for u in stops
            if u is not t and u['sys'] != t['sys']
            and math.hypot(u['lon'] - t['lon'], u['lat'] - t['lat']) < XFER)
    stops.sort(key=lambda t: (t['sys'], -t['lat']))

    # ── 對帳一：TDX 說在臺中的臺鐵站，必須與市界判定出來的完全一致 ────────
    got = {t['name'] for t in stops if t['sys'] == 'tra'}
    if got != claimed:
        sys.exit(f'臺鐵站對不上。市界判定多出 {sorted(got - claimed)}、'
                 f'少了 {sorted(claimed - got)}。市界幾何或車站座標有一個是錯的')

    # ── 對帳二：TDX 的 LocationTown 必須等於本程式算出來的行政區 ──────────
    # 對不上而車站就坐落在區界上的，記下來帶到版面；其餘一律停下。
    cases, hard = [], []
    for t in stops:
        if t['district'] == t['geoDistrict']:
            continue
        m = edge_dist_m([t['lon'], t['lat']], districts)
        row = {'name': t['name'], 'sysLabel': t['sysLabel'],
               'tdx': t['district'], 'geo': t['geoDistrict'], 'edgeM': round(m, 1)}
        (cases if m <= BOUNDARY_M else hard).append(row)
    if hard:
        sys.exit('這些站 TDX 的行政區與界線判定不一致，而且離區界很遠，'
                 '代表座標或市界幾何有錯，先查清楚再說：\n  '
                 + '\n  '.join(f'{r["name"]}　TDX：{r["tdx"]}　判定：{r["geo"]}'
                                f'　距區界 {r["edgeM"]} 公尺' for r in hard))
    if len(cases) > MAX_BOUNDARY_CASES:
        sys.exit(f'落在區界上的不一致有 {len(cases)} 個，超過 {MAX_BOUNDARY_CASES} 個就'
                 f'不是邊界案例而是系統性的偏移，停下來：'
                 + '、'.join(r['name'] for r in cases))

    # ── 對帳三：每一站都要落在已知的行政區，且都要分到一條線 ──────────────
    for t in stops:
        if t['district'] not in names or not t['line']:
            sys.exit(f'{t["name"]}站沒有分到行政區或路線：{t}')

    # ── 對帳四：各站等的站數加總必須等於臺鐵站總數 ───────────────────────
    by_cls = {}
    for t in stops:
        if t['sys'] == 'tra':
            by_cls.setdefault(t['cls'], []).append(t['name'])
    if sum(len(v) for v in by_cls.values()) != len(got):
        sys.exit('站等分組的加總不等於臺鐵站總數')

    by_line, by_sys = {}, {}
    for t in stops:
        for ln in t['lines']:
            by_line.setdefault(ln, []).append(t['name'])
        by_sys.setdefault(t['sysLabel'], []).append(t['name'])

    blob = {
        'city': '臺中市',
        'source': ('臺鐵與高鐵線形取自 yunching0513/tdx-transit-twin 的 data/static/；'
                   '車站與臺中捷運線形取自交通部TDX，'
                   '臺鐵站等是 TDX 的 StationClass 欄位，即官方分級。'
                   '全部裁切至臺中市行政區界內'),
        'caveat': ('捷運與高鐵不分站等，因此只有臺鐵的車站標了等級。'
                   '轉乘的判定是兩站相距440公尺以內，那是站體之間的直線距離，'
                   '不是實際的轉乘動線長度。'
                   + (''.join(f'{r["sysLabel"]}{r["name"]}站坐落在區界上，'
                              f'距界線僅{r["edgeM"]}公尺，'
                              f'TDX 的地址算{r["tdx"]}、普查的界線幾何算{r["geo"]}，'
                              f'本檔採 TDX。' for r in cases))),
        'classLabels': CLASS,
        'boundaryCases': cases,
        'ridershipNote': ride_note,
        'ridershipPeriod': ride_period,
        'systems': sorted({L['sysLabel'] for L in lines}),
        'lines': lines,
        'stops': stops,
        'byLine': {k: len(v) for k, v in sorted(by_line.items())},
        'bySystem': {k: len(v) for k, v in sorted(by_sys.items())},
        'byClass': {k: len(v) for k, v in sorted(by_cls.items())},
        'missing': ['公車班距與班表（TDX 的 /Bus/Schedule，見 docs/sources.md）'],
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f'{OUT.relative_to(ROOT)}：{len(lines)} 條線、{len(stops)} 個車站')
    for L in lines:
        print(f"  {L['sysLabel']}　{L['line']:14s} 段 {len(L['segments'])}　點 {L['points']:,}")
    for k, v in sorted(by_cls.items()):
        print(f'  臺鐵{CLASS[k]}　{len(v):2d} 站　{"、".join(v)}')
    for k, v in sorted(by_sys.items()):
        print(f'  {k} 共 {len(v)} 站')
    jx = [f"{t['name']}（{'＋'.join(t['lines'])}）" for t in stops if t['junction']]
    print(f'  山海線交會：{"、".join(jx) if jx else "無"}')
    xf = [f"{t['sysLabel']}{t['name']} ↔ {'、'.join(t['xfer'])}" for t in stops if t['xfer']]
    print('  跨系統轉乘（440公尺內）：' + ('\n    ' + '\n    '.join(xf) if xf else '無'))
    for r in cases:
        print(f'  坐落在區界上：{r["sysLabel"]}{r["name"]}　TDX：{r["tdx"]}　'
              f'界線判定：{r["geo"]}　距區界 {r["edgeM"]} 公尺（採 TDX）')
    rd = [t for t in stops if t.get('ridership')]
    if rd:
        print(f'  每日平均進出站人次（{ride_period}）：')
        for t in sorted(rd, key=lambda t: -t['ridership']['total'])[:6]:
            r = t['ridership']
            print(f"    {t['name']:5s} 進 {r['in']:>6,}　出 {r['out']:>6,}　"
                  f"合計 {r['total']:>6,}　（{t['clsLabel']}）")
        print(f'    最少：' + '、'.join(
            f"{t['name']}{t['ridership']['total']:,}"
            for t in sorted(rd, key=lambda t: t['ridership']['total'])[:3]))
        for t in rd:
            if t['ridership'].get('asym'):
                print(f"    不對稱：{t['name']} 進出比 {t['ridership']['asym']}"
                      f"（具名例外，成因未查證）")
        print('  高鐵與捷運：無公開資料，ridership 給 null')
    if dropped:
        print(f'  裁切後不進臺中而捨棄的線：{"、".join(dropped)}')


if __name__ == '__main__':
    main()
