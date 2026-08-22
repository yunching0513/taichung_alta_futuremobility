#!/usr/bin/env python3
"""算車站方圓500公尺覆蓋了多少人口。

    python3 scripts/prep_access.py

輸入 data/tc_rail.json（42個車站的座標）與 data/tc_villages.json（里的界線與人口）。
輸出 data/tc_access.json。

── 覆蓋怎麼算，為什麼這個選擇會改變答案 ──────────────────────────────
「方圓500公尺覆蓋多少人」聽起來像一個事實，其實是一個**方法選擇的結果**。
本檔算兩種，兩種都寫出來：

**其一，面積比例分配（areal，本檔的主數字）。**
把每一個里切成格點，數有多少比例的格點落在任一車站500公尺內，
再把那個比例乘上該里的人口。這假設**里內人口均勻分布**，那是一個假設不是事實：
一個里若人集中在車站那一側，這個算法會低估；集中在另一側則高估。
在都市的小里（0.04至0.5平方公里）這個假設還算可以，山區的大里則不行。

**其二，里重心法（centroid，對照用）。**
里的重心落在500公尺內就整個里算進來，否則整個里算出去。
這是最常見的偷懶做法，本檔把它算出來不是要用它，是要讓讀者看見
**同一個問題換一個方法可以差多少**。差得越多，代表那個數字越不該當成事實引用。

── 三個必須跟著數字一起講的限制 ──────────────────────────────────────
其一，**500公尺是直線距離，不是步行距離。** 實際走路要繞過街廓、河川與鐵路本身，
一般經驗值是直線距離的1.2至1.4倍。因此這個數字是「步行500公尺可及」的**上限**，
真正走得到的人比這裡算出來的少。

其二，**只有457個里算得準。** 臺中625個里裡，拿得到界線的只有593個多邊形，
7個區因此退回區級（見 prep_villages.py），那7個區佔全市人口三成。
其中潭子、沙鹿、后里、清水四個區裡有臺鐵車站，不能當作零。

本檔對那7個區照樣算面積比例，唯**把它明確標成下界而不是估計值**：
區級的均勻分布假設在這裡一定低估，因為車站蓋在市鎮中心，
而市鎮中心的人口密度遠高於整個區的平均。因此全市的數字寫成
「至少多少」，而不是一個看起來很確定的百分比。

其三，車站只有軌道，不含公車站牌。公車站牌13,877個幾乎覆蓋全市，
把它算進來會讓這個指標失去意義；真正該問的是「有多少人住在**高頻**運輸的旁邊」，
而公車的高頻路線要另外定義。
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAIL = ROOT / 'data' / 'tc_rail.json'
VILL = ROOT / 'data' / 'tc_villages.json'
OUT = ROOT / 'data' / 'tc_access.json'

RADII = [400, 500, 800, 1000]      # 公尺。500是題目，其餘拿來看這個數字對半徑有多敏感
MAIN_R = 500
DEG = 111320.0                     # 一度緯度約幾公尺
MIN_PTS = 400                      # 每個里至少要取到這麼多格點，否則比例不穩
MAX_PTS = 6000                     # 上限，免得和平區那種336平方公里的里把時間吃光

SYSTEMS = [('all', '全部車站'), ('tra', '臺鐵'), ('metro', '捷運'), ('thsr', '高鐵')]


def load(p):
    if not p.exists():
        sys.exit(f'缺少 {p.relative_to(ROOT)}')
    return json.loads(p.read_text(encoding='utf-8'))


def inside(x, y, rings):
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


def bbox(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(rings):
    best, area = rings[0], -1
    for r in rings:
        a = abs(sum(r[j][0] * r[(j + 1) % len(r)][1] - r[(j + 1) % len(r)][0] * r[j][1]
                    for j in range(len(r)))) / 2
        if a > area:
            area, best = a, r
    return (sum(p[0] for p in best) / len(best), sum(p[1] for p in best) / len(best))


def main():
    rail = load(RAIL)
    vill = load(VILL)
    stops = rail['stops']
    units = vill['units']
    fine = [u for u in units if not u.get('villages')]
    coarse = [u for u in units if u.get('villages')]
    if not fine:
        sys.exit('一個有界線的里都沒有')

    lat0 = sum(p[1] for u in fine for r in u['rings'] for p in r) \
        / sum(len(r) for u in fine for r in u['rings'])
    kx = math.cos(lat0 * math.pi / 180)

    def m_per_deg_x():
        return DEG * kx

    results = {}
    for sysk, syszh in SYSTEMS:
        pts = [(s['lon'], s['lat']) for s in stops if sysk == 'all' or s['sys'] == sysk]
        if not pts:
            sys.exit(f'{syszh}一個車站都沒有')
        per_r = {}
        for R in RADII:
            dx = R / m_per_deg_x()          # R 公尺換算成經度的度數
            dy = R / DEG
            cov_pop = cen_pop = 0.0
            cov_area = 0.0
            n_full = n_part = 0
            for u in fine:
                x0, y0, x1, y1 = bbox(u['rings'])
                # 先粗篩：這個里的外接矩形擴張 R 之後碰不到任何車站，就整個跳過。
                # 大部分的里都在這一步被排除，剩下的才真的去取格點。
                near = [(sx, sy) for sx, sy in pts
                        if x0 - dx <= sx <= x1 + dx and y0 - dy <= sy <= y1 + dy]
                cx, cy = centroid(u['rings'])
                if any(math.hypot((sx - cx) * m_per_deg_x(), (sy - cy) * DEG) <= R
                       for sx, sy in near):
                    cen_pop += u['pop']
                if not near:
                    continue
                # 格點：邊長取到讓格點數落在 MIN_PTS 與 MAX_PTS 之間
                w, h = (x1 - x0) * kx, (y1 - y0)
                step = math.sqrt(w * h / MIN_PTS) if w * h > 0 else dx
                if w * h / (step * step) > MAX_PTS:
                    step = math.sqrt(w * h / MAX_PTS)
                sx_n = max(2, int(w / step)), max(2, int(h / step))
                nx, ny = sx_n
                tot = hits = 0
                for i in range(nx):
                    px = x0 + (i + 0.5) * (x1 - x0) / nx
                    for j in range(ny):
                        py = y0 + (j + 0.5) * (y1 - y0) / ny
                        if not inside(px, py, u['rings']):
                            continue
                        tot += 1
                        if any(math.hypot((sx - px) * m_per_deg_x(), (sy - py) * DEG) <= R
                               for sx, sy in near):
                            hits += 1
                if tot == 0:
                    # 里太小，格點一個都沒落進去。改用重心當代表點，並記下來。
                    tot, hits = 1, 1 if any(
                        math.hypot((sx - cx) * m_per_deg_x(), (sy - cy) * DEG) <= R
                        for sx, sy in near) else 0
                f = hits / tot
                cov_pop += u['pop'] * f
                cov_area += u['area'] * f
                if f >= 0.999:
                    n_full += 1
                elif f > 0:
                    n_part += 1
            per_r[R] = {'pop': round(cov_pop), 'centroidPop': round(cen_pop),
                        'areaKm2': round(cov_area, 2),
                        'fullVillages': n_full, 'partVillages': n_part}
        results[sysk] = {'zh': syszh, 'stations': len(pts), 'byRadius': per_r}

    # ── 退回區級的那7個區：照樣算面積比例，唯結果只當下界 ────────────────
    # 車站蓋在市鎮中心，而市鎮中心的密度遠高於整個區的平均，
    # 所以「用區的平均密度乘上覆蓋面積」一定低估。標成 floor，不當估計值。
    coarse_cov = {}
    for R in RADII:
        dx, dy = R / m_per_deg_x(), R / DEG
        tot_c = 0.0
        for u in coarse:
            x0, y0, x1, y1 = bbox(u['rings'])
            near = [(sx, sy) for sx, sy in [(t['lon'], t['lat']) for t in stops]
                    if x0 - dx <= sx <= x1 + dx and y0 - dy <= sy <= y1 + dy]
            if not near:
                continue
            w, h = (x1 - x0) * kx, (y1 - y0)
            step = math.sqrt(w * h / MAX_PTS)
            nx, ny = max(2, int(w / step)), max(2, int(h / step))
            inn = hit = 0
            for i in range(nx):
                px = x0 + (i + 0.5) * (x1 - x0) / nx
                for j in range(ny):
                    py = y0 + (j + 0.5) * (y1 - y0) / ny
                    if not inside(px, py, u['rings']):
                        continue
                    inn += 1
                    if any(math.hypot((sx - px) * m_per_deg_x(), (sy - py) * DEG) <= R
                           for sx, sy in near):
                        hit += 1
            if inn:
                tot_c += u['pop'] * hit / inn
        coarse_cov[R] = round(tot_c)

    # ── 每一站自己的覆蓋人口。站與站的緩衝區會重疊，所以這幾個數字**不可以相加**：
    # 相加會把轉乘站附近的人算好幾次。這裡回答的是「這一站旁邊住了多少人」。
    # 車站所在的區若沒有里界，這一站的覆蓋人口是**算不出來**，不是0。
    # 后里、清水、潭子、沙鹿四個區有臺鐵車站，卻正好在缺界線的那七個區裡。
    coarse_names = {u['name'] for u in coarse}
    per_stop = []
    R = MAIN_R
    dx, dy = R / m_per_deg_x(), R / DEG
    for t in stops:
        tot = 0.0
        for u in fine:
            x0, y0, x1, y1 = bbox(u['rings'])
            if not (x0 - dx <= t['lon'] <= x1 + dx and y0 - dy <= t['lat'] <= y1 + dy):
                continue
            w, h = (x1 - x0) * kx, (y1 - y0)
            step = math.sqrt(w * h / MIN_PTS) if w * h > 0 else dx
            if w * h / (step * step) > MAX_PTS:
                step = math.sqrt(w * h / MAX_PTS)
            nx, ny = max(2, int(w / step)), max(2, int(h / step))
            inn = hit = 0
            for i in range(nx):
                px = x0 + (i + 0.5) * (x1 - x0) / nx
                for j in range(ny):
                    py = y0 + (j + 0.5) * (y1 - y0) / ny
                    if not inside(px, py, u['rings']):
                        continue
                    inn += 1
                    if math.hypot((t['lon'] - px) * m_per_deg_x(),
                                  (t['lat'] - py) * DEG) <= R:
                        hit += 1
            if inn:
                tot += u['pop'] * hit / inn
        unknown = t['district'] in coarse_names
        per_stop.append({'name': t['name'], 'sys': t['sys'], 'sysLabel': t['sysLabel'],
                         'district': t['district'], 'cls': t.get('clsLabel'),
                         'pop': None if unknown else round(tot),
                         'why': '所在的區沒有里界，算不出來' if unknown else None,
                         'ridership': (t.get('ridership') or {}).get('total')})
    per_stop.sort(key=lambda x: (x['pop'] is None, -(x['pop'] or 0)))

    fine_pop = sum(u['pop'] for u in fine)
    coarse_pop = sum(u['pop'] for u in coarse)
    total_pop = fine_pop + coarse_pop
    fine_area = sum(u['area'] for u in fine)

    # ── 對帳一：覆蓋人口不得超過母體，且半徑越大覆蓋越多 ──────────────
    for sysk, r in results.items():
        for R, v in r['byRadius'].items():
            if v['pop'] > fine_pop + 0.5:
                sys.exit(f'{sysk} {R}公尺的覆蓋人口 {v["pop"]:,} 超過母體 {fine_pop:,}')
        rs = sorted(r['byRadius'])
        for a, b in zip(rs, rs[1:]):
            if r['byRadius'][b]['pop'] < r['byRadius'][a]['pop'] - 0.5:
                sys.exit(f'{sysk}：{b}公尺的覆蓋人口比 {a}公尺還少，格點取樣有問題')

    # ── 對帳二：全部車站的覆蓋，不得少於任一單一系統 ────────────────────
    for sysk in ('tra', 'metro', 'thsr'):
        for R in RADII:
            if results['all']['byRadius'][R]['pop'] < results[sysk]['byRadius'][R]['pop'] - 0.5:
                sys.exit(f'全部車站在{R}公尺的覆蓋，比只有{sysk}還少，聯集算錯了')

    # ── 對帳三：各系統分開加總，必須大於等於聯集（重疊會讓它大於） ────────
    for R in RADII:
        sep = sum(results[s]['byRadius'][R]['pop'] for s in ('tra', 'metro', 'thsr'))
        if sep < results['all']['byRadius'][R]['pop'] - 0.5:
            sys.exit(f'{R}公尺：三個系統分開加總 {sep:,.0f} 小於聯集 '
                     f'{results["all"]["byRadius"][R]["pop"]:,}，不可能')

    m = results['all']['byRadius'][MAIN_R]
    blob = {
        'city': '臺中市',
        'period': vill['period'],
        'radiusM': MAIN_R,
        'radii': RADII,
        'source': (f'車站座標取自 data/tc_rail.json（臺鐵、臺中捷運、高鐵共{len(stops)}站，'
                   f'來源交通部TDX）；人口與界線取自 data/tc_villages.json'
                   f'（內政部戶政司{vill["period"]}逐村里、g0v twVillage1982 界線）'),
        'method': ('面積比例分配：把每個里切成格點，數落在車站緩衝區內的比例，'
                   '再乘上該里的人口。假設里內人口均勻分布。'
                   '另附里重心法作為方法敏感度的對照。'),
        'caveat': (f'{MAIN_R}公尺是直線距離不是步行距離，實際走路一般是直線的1.2至1.4倍，'
                   f'因此這是可及人口的上限。'
                   f'母體只有畫得到界線的{len(fine)}個里、{fine_pop:,}人，'
                   f'佔全市{fine_pop / total_pop * 100:.1f}%；'
                   f'另外{len(coarse)}個區退回區級、共{coarse_pop:,}人，'
                   f'本檔不拿區級的均勻分布去頂替，那部分的覆蓋率是未知不是零。'
                   f'車站只計軌道，不含公車站牌。'),
        'universe': {'villages': len(fine), 'pop': fine_pop, 'areaKm2': round(fine_area, 1),
                     'coarseDistricts': len(coarse), 'coarsePop': coarse_pop,
                     'cityPop': total_pop,
                     'sharePop': round(fine_pop / total_pop * 100, 1)},
        # 退回區級那7個區的覆蓋，只當下界：區級均勻分布在這裡一定低估
        'coarseFloor': coarse_cov,
        'cityFloor': {R: {'pop': results['all']['byRadius'][R]['pop'] + coarse_cov.get(R, 0),
                          'pct': round((results['all']['byRadius'][R]['pop']
                                        + coarse_cov.get(R, 0)) / total_pop * 100, 2)}
                      for R in RADII},
        'perStop': per_stop,
        'systems': results,
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    print(f'{OUT.relative_to(ROOT)}')
    print(f'  母體：{len(fine)} 個里、{fine_pop:,} 人（全市{total_pop:,}人的'
          f'{fine_pop / total_pop * 100:.1f}%）、{fine_area:,.0f} km²')
    print(f'  另有 {len(coarse)} 個區退回區級，{coarse_pop:,} 人，覆蓋率未知\n')
    print(f'  ── {MAIN_R} 公尺（直線） ──')
    for sysk, syszh in SYSTEMS:
        v = results[sysk]['byRadius'][MAIN_R]
        print(f'  {syszh:6s}（{results[sysk]["stations"]:2d}站）'
              f'面積比例 {v["pop"]:>9,} 人　{v["pop"] / fine_pop * 100:5.2f}%　'
              f'　里重心法 {v["centroidPop"]:>9,} 人　{v["centroidPop"] / fine_pop * 100:5.2f}%')
    print(f'\n  ── 全市（母體的覆蓋 ＋ 那7個區的下界） ──')
    for R in RADII:
        c = blob['cityFloor'][R]
        print(f'  {R:>4d} 公尺　至少 {c["pop"]:>9,} 人　{c["pct"]:5.2f}%　'
              f'（其中那7個區貢獻 {coarse_cov.get(R, 0):,} 人，是下界不是估計值）')
    print(f'\n  ── 覆蓋人口最多的十個車站（緩衝區會重疊，**不可以相加**） ──')
    for t in per_stop[:10]:
        rd = f'　每日進出 {t["ridership"]:,}' if t['ridership'] else '　每日進出 無公開資料'
        print(f'  {t["sysLabel"]}{t["name"]:8s} {t["district"]:5s} '
              f'{t["pop"]:>7,} 人{rd}')
    known = [t for t in per_stop if t['pop'] is None or t['pop'] is not None]
    lo = [t for t in per_stop if t['pop'] is not None][-6:]
    print(f'  覆蓋最少的六站：'
          + '、'.join(f'{t["sysLabel"]}{t["name"]}{t["pop"]:,}人' for t in lo))
    na = [t for t in per_stop if t['pop'] is None]
    print(f'  算不出來的 {len(na)} 站（所在的區沒有里界）：'
          + '、'.join(f'{t["sysLabel"]}{t["name"]}' for t in na))
    # 進出站人次與周邊人口的落差，是這一節最值得看的一件事
    both = [t for t in per_stop if t['pop'] and t['ridership']]
    both.sort(key=lambda t: -(t['ridership'] / max(1, t['pop'])))
    print(f'\n  ── 每日進出人次 ÷ 500公尺內人口，最高的五站 ──')
    for t in both[:5]:
        print(f'  {t["sysLabel"]}{t["name"]:6s} 進出 {t["ridership"]:>7,}　'
              f'周邊 {t["pop"]:>7,} 人　比值 {t["ridership"] / t["pop"]:5.2f}')
    print(f'\n  ── 全部車站，換半徑 ──')
    for R in RADII:
        v = results['all']['byRadius'][R]
        print(f'  {R:>4d} 公尺　{v["pop"]:>9,} 人　{v["pop"] / fine_pop * 100:5.2f}%　'
              f'覆蓋面積 {v["areaKm2"]:>7,.1f} km²（{v["areaKm2"] / fine_area * 100:4.1f}%）　'
              f'完整覆蓋 {v["fullVillages"]:3d} 里、部分覆蓋 {v["partVillages"]:3d} 里')


if __name__ == '__main__':
    main()
