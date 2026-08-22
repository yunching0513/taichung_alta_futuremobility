# TDX 原始檔

由 `scripts/fetch_tdx.py` 抓下來，原樣存放，不做加工。
金鑰不在這裡也不在版控裡，見專案 README 的「TDX 金鑰放哪裡」。

- `metro_network_tmrt.json` — 臺中捷運的路線與車站關聯。補上目前完全缺席的綠線
- `metro_station_tmrt.json` — 臺中捷運車站，含經緯度
- `metro_shape_tmrt.json` — 臺中捷運的路線線形（WKT）。畫得出綠線的實際走向
- `thsr_station.json` — 高鐵車站含經緯度。補上目前有線形沒有站點的高鐵臺中站
- `tra_station.json` — 臺鐵車站。TDX 這一份含 StationClass，那就是官方站等
- `bus_stop_taichung.json` — 臺中公車站牌（單一站牌，含經緯度）
- `bus_station_taichung.json` — 臺中公車站位（同一路口的站牌群）
- `bus_route_taichung.json` — 臺中公車路線清單
- `bus_shape_taichung.json` — 臺中公車路線線形。要畫路線圖就靠這一份
- `bus_schedule_taichung.json` — 臺中公車班表與班距。線寬按頻率畫粗細就靠這一份
