#!/usr/bin/env python3
"""把臺中29個行政區的基本盤整理成一份中間檔。

    python3 scripts/prep_districts.py

輸入是 data_TW/from_housing/ 底下的三份切片，來源與擷取條件寫在各檔的 _upstream 欄位：

    census_109.json      主計總處《人口及住宅普查》民國109年   住宅、家戶、空屋、屋齡
    signal_112_11.json   內政部電信信令                        日間、夜間、上午、假日人口
    geometry.json        鄉鎮市區界，已簡化                    畫地圖用

輸出 data/tc_districts.json，29個區各一筆。

── 為什麼移動放在前面 ──────────────────────────────────────────────────
臺中全市的日夜間人口比是0.997，看起來是一個通勤圈與市界重合、自給自足的城市。
唯29個區的比值從外埔區的0.819到西屯區的1.198，全距0.379：
**全市那個接近1的數字，是兩組方向相反的失衡互相抵銷出來的。**
以縣市為單位討論臺中的移動，等於把這件事整個抹掉，所以本專案的空間單位是區。

── 三個期別，不能相減 ──────────────────────────────────────────────
普查是民國109年11月、信令是112年11月，兩者差兩年。
本檔把兩邊的數字放在同一筆紀錄裡是為了方便查閱，**不是為了讓它們相減**。
同一格內的比較成立，跨格比較要先看 periods 欄位。

── 一個算得出來、唯不宜過度解讀的相關 ────────────────────────────────
29個區的普查空屋率與日夜間人口比，相關係數只有0.28，屬弱相關。
西屯區與中區是高日夜比配高空屋率，清水區卻是低日夜比配高空屋率，方向相反。
因此本檔把相關係數一併輸出，用意是提醒版面不要把「白天有人的地方」
直接講成「晚上空著的地方」；那個因果這批資料撐不起來。
"""
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'data_TW' / 'from_housing'
OUT = ROOT / 'data' / 'tc_districts.json'

CENSUS = SRC / 'census_109.json'
SIGNAL = SRC / 'signal_112_11.json'
GEOM = SRC / 'geometry.json'

# 普查與信令的期別。寫進輸出讓版面沒辦法不標。
PERIODS = {
    'census': '民國109年11月',
    'signal': '民國112年11月',
}


def load(path):
    if not path.exists():
        sys.exit(f'缺少輸入檔：{path.relative_to(ROOT)}')
    return json.loads(path.read_text(encoding='utf-8'))


def pearson(xs, ys):
    """相關係數。兩個數列長度不同或幾乎沒有變異就回 None，不硬算。"""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = sum((a - mx) ** 2 for a in xs) ** .5
    sy = sum((b - my) ** 2 for b in ys) ** .5
    if sx == 0 or sy == 0:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (sx * sy), 3)


def main():
    census, signal, geom = load(CENSUS), load(SIGNAL), load(GEOM)
    C = {r['name']: r for r in census['rows']}
    S = {r['name']: r for r in signal['rows']}
    G = {r['name']: r for r in geom['rows']}

    names = sorted(set(C) & set(S) & set(G))
    missing = (set(C) | set(S) | set(G)) - set(names)
    if missing:
        sys.exit(f'三份切片的區名對不上，缺的是：{sorted(missing)}')
    if len(names) != 29:
        sys.exit(f'臺中應該有29個區，這裡是 {len(names)} 個')

    rows = []
    for n in names:
        c, s, g = C[n], S[n], G[n]
        ages = c['ageAll']
        total_age = sum(ages)
        if abs(total_age - c['houses']) > 1:
            sys.exit(f'{n} 的屋齡分組加總 {total_age:,} 不等於住宅數 {c["houses"]:,}')
        rows.append({
            'name': n,
            'houses': c['houses'],
            'households': c['households'],
            'residents': c['residents'],
            'vacancy': c['vacancy'],
            'idle': c['idle'],
            'perHousehold': c['perHousehold'],
            # 屋齡五組：40年以上／30–39／20–29／10–19／未滿10年
            'ageAll': ages,
            'old40': round(ages[0] / c['houses'] * 100, 2),
            'new10': round(ages[4] / c['houses'] * 100, 2),
            'avgAreaAll': c['avgAreaAll'],
            # 移動
            'dayWork': s['dayWork'],
            'nightWork': s['nightWork'],
            'ratio': s['ratio'],
            'net': s['dayWork'] - s['nightWork'],
            'morningRatio': s['morningRatio'],
            'ratioWeekend': s['ratioWeekend'],
            'area': s['area'],
            'nightDensity': s['nightDensity'],
            'rings': g['rings'],
        })

    # ── 對帳：29 區加總必須等於全市，且比率要能由分子分母還原 ──
    tot_houses = sum(r['houses'] for r in rows)
    tot_hh = sum(r['households'] for r in rows)
    for r in rows:
        back = r['idle'] / r['houses'] * 100
        if abs(back - r['vacancy']) > 0.02:
            sys.exit(f'{r["name"]} 的空屋率 {r["vacancy"]} 與 idle/houses 算出來的 {back:.2f} 對不上')
        back_ratio = r['dayWork'] / r['nightWork']
        if abs(back_ratio - r['ratio']) > 0.002:
            sys.exit(f'{r["name"]} 的日夜比 {r["ratio"]} 與 day/night 算出來的 {back_ratio:.3f} 對不上')

    ratios = [r['ratio'] for r in rows]
    vacs = [r['vacancy'] for r in rows]
    blob = {
        'city': '臺中市',
        'periods': PERIODS,
        'source': ('主計總處《人口及住宅普查》民國109年、內政部電信信令民國112年11月，'
                   '經 yunching0513/housing 解析後取臺中市29區'),
        'caveat': ('普查與信令差兩年，同一筆紀錄裡的兩組數字不能相減；'
                   '日夜間人口比是工作日的日間除以夜間，反映的是通勤的淨流向，'
                   '給不出起訖對，答不了「白天走掉的人去了哪一區」。'),
        'ageLabels': census['ageLabels'],
        'totals': {
            'houses': tot_houses,
            'households': tot_hh,
            'residents': sum(r['residents'] for r in rows),
            'idle': sum(r['idle'] for r in rows),
            'vacancy': round(sum(r['idle'] for r in rows) / tot_houses * 100, 2),
            'dayWork': sum(r['dayWork'] for r in rows),
            'nightWork': sum(r['nightWork'] for r in rows),
        },
        'spread': {
            'ratioMin': min(ratios), 'ratioMax': max(ratios),
            'ratioRange': round(max(ratios) - min(ratios), 3),
            'vacancyMin': min(vacs), 'vacancyMax': max(vacs),
            'vacancyRange': round(max(vacs) - min(vacs), 2),
        },
        # 弱相關。輸出它是為了讓版面必須說出「這兩件事關係不強」。
        'corrVacancyRatio': pearson(ratios, vacs),
        'bounds': [
            min(p[0] for r in rows for ring in r['rings'] for p in ring),
            min(p[1] for r in rows for ring in r['rings'] for p in ring),
            max(p[0] for r in rows for ring in r['rings'] for p in ring),
            max(p[1] for r in rows for ring in r['rings'] for p in ring),
        ],
        'districts': rows,
    }
    blob['totals']['ratio'] = round(blob['totals']['dayWork'] / blob['totals']['nightWork'], 3)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding='utf-8')

    t = blob['totals']
    print(f'{OUT.relative_to(ROOT)}：{len(rows)} 個區')
    print(f"  住宅 {t['houses']:,}　家戶 {t['households']:,}　常住人口 {t['residents']:,}")
    print(f"  空屋率 {t['vacancy']}%　全市日夜比 {t['ratio']}"
          f"（區級 {blob['spread']['ratioMin']}–{blob['spread']['ratioMax']}，"
          f"全距 {blob['spread']['ratioRange']}）")
    print(f"  空屋率與日夜比的相關係數 {blob['corrVacancyRatio']}（弱相關）")


if __name__ == '__main__':
    main()
