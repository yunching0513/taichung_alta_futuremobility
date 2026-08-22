#!/usr/bin/env python3
"""把 src/ 的模板與 data/ 的中間檔組成單一檔 HTML。

    python3 scripts/build.py

產出 dist/*.html：單一檔案、零外部請求（字型除外，見下），斷網也開得起來。
資料以 <script type="application/json"> 內嵌，不用 fetch，因此 file:// 直接點開就能看。

字型是唯一的外部請求：Noto Sans TC 與 Space Grotesk 走 Google Fonts。
兩者都在 CSS 裡給了系統字型的後備堆疊，連不到網路時版面仍然成立，
只是字重對比會弱一些。這是照 VZT 風格指南的字體系統走，刻意保留的一個例外。

版面不直接讀 data_TW/：那是 prep_*.py 的事（見 README 的資料流向）。
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'src'
DATA = ROOT / 'data'
DIST = ROOT / 'dist'

PAGES = {
    'index.html': ('index.template.html', {
        '__TC_JSON__': 'tc_districts.json',
        '__RAIL_JSON__': 'tc_rail.json',
    }),
}


def main():
    if not SRC.exists():
        sys.exit('找不到 src/')
    DIST.mkdir(exist_ok=True)
    for out_name, (tpl_name, tokens) in PAGES.items():
        tpl = SRC / tpl_name
        if not tpl.exists():
            sys.exit(f'找不到模板 {tpl.relative_to(ROOT)}')
        html = tpl.read_text(encoding='utf-8')
        for token, filename in tokens.items():
            path = DATA / filename
            if not path.exists():
                sys.exit(f'{tpl_name} 要 {filename}，但 data/ 裡沒有——先跑對應的 prep 腳本')
            # 分隔符原樣內嵌，只擋掉會提前關閉 script 標籤的字串
            blob = json.dumps(json.loads(path.read_text(encoding='utf-8')),
                              ensure_ascii=False, separators=(',', ':'))
            html = html.replace(token, blob.replace('</', '<\\/'))
        left = re.findall(r'__[A-Z0-9_]+__', html)
        if left:
            sys.exit(f'{tpl_name} 還有沒替換的 token：{sorted(set(left))}')
        dest = DIST / out_name
        dest.write_text(html, encoding='utf-8')
        print(f'  {out_name:16s} {len(html) / 1024:6.0f} KB')
    print(f'產出在 {DIST.relative_to(ROOT)}/，單一檔案，點開就能看')


if __name__ == '__main__':
    main()
