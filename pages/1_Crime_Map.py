import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data_service import load_and_clean_data
from ui import setup_page, load_with_message, source_caption


# ============================================================
# 页面与在线数据
# ============================================================
setup_page("Crime Map", "🗺️")

st.write(
    "Explore crime patterns. Zoom out to summarize larger areas "
    "and zoom in to inspect smaller areas."
)

df = load_with_message(load_and_clean_data)
source_caption(df)

if df.empty:
    st.warning("No crime records are available.")
    st.stop()


# ============================================================
# 侧边栏筛选
# ============================================================
st.sidebar.header("Map Filters")

crime_name1_options = ["All"] + sorted(
    df["Crime Name1"]
    .dropna()
    .astype(str)
    .unique()
    .tolist()
)

selected_crime_name1 = st.sidebar.selectbox(
    "Crime Name1",
    crime_name1_options,
)

if selected_crime_name1 == "All":
    crime_name2_options = ["All"]
else:
    crime_name2_options = ["All"] + sorted(
        df.loc[
            df["Crime Name1"].astype(str).eq(selected_crime_name1),
            "Crime Name2",
        ]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

selected_crime_name2 = st.sidebar.selectbox(
    "Crime Name2",
    crime_name2_options,
)

valid_dates = df["Date"].dropna()

if valid_dates.empty:
    st.warning("No valid incident dates are available.")
    st.stop()

min_date = valid_dates.min().date()
max_date = valid_dates.max().date()

selected_date_range = st.sidebar.date_input(
    "Date Range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

start_hour, end_hour = st.sidebar.slider(
    "Hour of Day",
    min_value=0,
    max_value=23,
    value=(0, 23),
    step=1,
)


# ============================================================
# 应用筛选
# ============================================================
filtered_df = df

if selected_crime_name1 != "All":
    filtered_df = filtered_df.loc[
        filtered_df["Crime Name1"]
        .astype(str)
        .eq(selected_crime_name1)
    ]

if selected_crime_name2 != "All":
    filtered_df = filtered_df.loc[
        filtered_df["Crime Name2"]
        .astype(str)
        .eq(selected_crime_name2)
    ]

if (
    not isinstance(selected_date_range, (tuple, list))
    or len(selected_date_range) != 2
):
    st.info("Select both the start and end dates.")
    st.stop()

start_date, end_date = selected_date_range

filtered_df = filtered_df.loc[
    filtered_df["Date"].ge(pd.Timestamp(start_date))
    & filtered_df["Date"].lt(
        pd.Timestamp(end_date) + pd.Timedelta(days=1)
    )
    & filtered_df["Hour"].between(start_hour, end_hour)
]

st.caption(
    f"Selected hours: "
    f"{start_hour:02d}:00–{end_hour:02d}:59 (inclusive)."
)


# ============================================================
# 有效坐标和 ZIP
# ============================================================
columns = ["Incident ID", "Latitude", "Longitude"]

if "Zip Code" in filtered_df.columns:
    columns.append("Zip Code")

mapped = filtered_df.loc[
    filtered_df["Valid_Coordinates"].fillna(False),
    columns,
].copy()

for column in ["Latitude", "Longitude"]:
    mapped[column] = pd.to_numeric(
        mapped[column],
        errors="coerce",
    )

mapped = mapped.dropna(
    subset=["Incident ID", "Latitude", "Longitude"]
)

# Web Mercator 地图可表示的纬度范围
mapped = mapped.loc[
    mapped["Latitude"].between(-85.05112878, 85.05112878)
    & mapped["Longitude"].between(-180, 180)
].copy()

if "Zip Code" not in mapped.columns:
    mapped["Zip Code"] = pd.NA

# 兼容 20850、20850.0、20850-1234 等格式
zip_text = mapped["Zip Code"].astype("string").str.strip()

mapped["ZIP"] = zip_text.str.extract(
    r"^(\d{5})(?:-\d{4}|\.0+)?$",
    expand=False,
).fillna("Unknown")


# ============================================================
# 汇总指标
# ============================================================
distinct_incidents = filtered_df["Incident ID"].nunique()
mappable_incidents = mapped["Incident ID"].nunique()

map_coverage = (
    mappable_incidents / distinct_incidents * 100
    if distinct_incidents
    else 0
)

col1, col2, col3 = st.columns(3)

col1.metric("Distinct Incidents", f"{distinct_incidents:,}")
col2.metric("Mappable Incidents", f"{mappable_incidents:,}")
col3.metric("Map Coverage", f"{map_coverage:.1f}%")

st.divider()

if mapped.empty:
    st.warning("No mappable incidents match the selected filters.")
    st.stop()


# ============================================================
# 为浏览器准备紧凑的内存数据
# 同一案件使用相同的整数编号，以便跨坐标、跨网格去重
# ============================================================
mapped["Incident_Key"] = pd.factorize(
    mapped["Incident ID"],
    sort=False,
)[0]

mapped = mapped.drop_duplicates(
    subset=["Incident_Key", "Latitude", "Longitude", "ZIP"]
)

locations = (
    mapped.groupby(
        ["Latitude", "Longitude"],
        as_index=False,
        observed=True,
    )
    .agg(
        Incident_Keys=(
            "Incident_Key",
            lambda values: [
                int(value) for value in pd.unique(values)
            ],
        ),
        ZIPs=(
            "ZIP",
            lambda values: sorted(set(values.astype(str))),
        ),
    )
)

# 每个坐标：[纬度、经度、案件编号数组、ZIP数组]
payload = [
    [
        float(row.Latitude),
        float(row.Longitude),
        row.Incident_Keys,
        row.ZIPs,
    ]
    for row in locations.itertuples(index=False)
]

payload_json = json.dumps(
    payload,
    ensure_ascii=True,
    separators=(",", ":"),
    allow_nan=False,
).replace("<", "\\u003c")

st.caption(
    "Hover over an area to see its distinct incident count and "
    "ZIP codes recorded within it. Use + / − or the mouse wheel "
    "to change the aggregation scale."
)


# ============================================================
# 浏览器地图：热力图 + 动态网格悬停
# 不使用额外散点，不保存任何犯罪数据文件
# ============================================================
map_html = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">

<link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
>

<style>
    html, body {
        margin: 0;
        padding: 0;
        font-family: Arial, sans-serif;
    }

    #map {
        width: 100%;
        height: 700px;
        border-radius: 10px;
        background: #f3f4f6;
    }

    .map-info {
        background: rgba(255, 255, 255, 0.96);
        padding: 10px 12px;
        border-radius: 7px;
        box-shadow: 0 1px 8px rgba(0, 0, 0, 0.16);
        color: #253047;
        font-size: 12px;
        line-height: 1.6;
        max-width: 270px;
    }

    .area-tooltip {
        background: #202938;
        color: white;
        border: 0;
        border-radius: 7px;
        padding: 12px 14px;
        font-size: 13px;
        line-height: 1.65;
        max-width: 310px;
        white-space: normal;
    }

    .area-tooltip .count {
        font-size: 22px;
        font-weight: bold;
        color: #ffdb83;
    }

    .area-tooltip .note {
        font-size: 11px;
        color: #cbd5e1;
        margin-top: 5px;
    }

    .legend-gradient {
        height: 12px;
        width: 190px;
        border-radius: 4px;
        margin: 5px 0;
        background: linear-gradient(
            to right,
            #ffffb2,
            #fed976,
            #feb24c,
            #fd8d3c,
            #f03b20,
            #bd0026
        );
    }

    .legend-labels {
        display: flex;
        justify-content: space-between;
    }
</style>
</head>

<body>
<div id="map"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>

<script>
(function () {
    "use strict";

    const raw = __CRIME_PAYLOAD__;

    if (!window.L || !L.heatLayer) {
        document.getElementById("map").textContent =
            "Map libraries could not load. Check your connection and refresh.";
        return;
    }

    const map = L.map("map", {
        center: [39.13, -77.20],
        zoom: 10,
        minZoom: 7,
        maxZoom: 18,
        zoomSnap: 1,
        zoomDelta: 1,
        scrollWheelZoom: true,
        preferCanvas: true
    });

    L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        {
            attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright">' +
                'OpenStreetMap</a> contributors &copy; ' +
                '<a href="https://carto.com/attributions">CARTO</a>',
            subdomains: "abcd",
            maxZoom: 20
        }
    ).addTo(map);

    L.control.scale({
        imperial: false,
        position: "bottomleft"
    }).addTo(map);

    // 在 zoom=0 时投影一次，以后缩放只需要乘以比例
    const points = raw.map(function (row) {
        const projected = map.project([row[0], row[1]], 0);
        return {
            lat: row[0],
            lon: row[1],
            x: projected.x,
            y: projected.y,
            ids: row[2],
            zips: row[3]
        };
    });

    // 热力图仍由真实记录坐标生成，不移动到网格中心
    const heatPoints = points.map(function (point) {
        return [point.lat, point.lon, point.ids.length];
    });

    let maxPointCount = 1;
    for (const point of points) {
        maxPointCount = Math.max(maxPointCount, point.ids.length);
    }

    const heat = L.heatLayer(heatPoints, {
        radius: 25,
        blur: 18,
        minOpacity: 0.12,
        max: maxPointCount,
        maxZoom: map.getZoom(),
        gradient: {
            0.10: "#ffffb2",
            0.30: "#fed976",
            0.50: "#feb24c",
            0.70: "#fd8d3c",
            0.85: "#f03b20",
            1.00: "#bd0026"
        }
    }).addTo(map);

    // 透明网格位于热力图上方，仅用于悬停和边界提示
    map.createPane("areaPane");
    map.getPane("areaPane").style.zIndex = 450;

    const areaRenderer = L.canvas({
        pane: "areaPane",
        padding: 0.2
    });

    const areaLayer = L.layerGroup().addTo(map);

    const info = L.control({position: "topright"});
    let infoElement;

    info.onAdd = function () {
        infoElement = L.DomUtil.create("div", "map-info");
        L.DomEvent.disableClickPropagation(infoElement);
        L.DomEvent.disableScrollPropagation(infoElement);
        return infoElement;
    };
    info.addTo(map);

    const legend = L.control({position: "bottomright"});
    legend.onAdd = function () {
        const div = L.DomUtil.create("div", "map-info");
        div.innerHTML =
            "<b>Relative crime density</b>" +
            '<div class="legend-gradient"></div>' +
            '<div class="legend-labels"><span>Low</span>' +
            "<span>High</span></div>";
        L.DomEvent.disableClickPropagation(div);
        return div;
    };
    legend.addTo(map);

    // 每个整数缩放级别上，网格约为 64×64 屏幕像素。
    // 放大一级：地面边长减半，原网格拆成四个子网格。
    const CELL_PIXELS = 64;

    let activeZoom = null;
    let cells = [];

    function makeBounds(gx, gy, zoom) {
        const northwest = map.unproject(
            [gx * CELL_PIXELS, gy * CELL_PIXELS],
            zoom
        );
        const southeast = map.unproject(
            [(gx + 1) * CELL_PIXELS, (gy + 1) * CELL_PIXELS],
            zoom
        );
        return L.latLngBounds(northwest, southeast);
    }

    function rebuildAggregation(zoom) {
        const scale = Math.pow(2, zoom);
        const grouped = new Map();

        for (const point of points) {
            const gx = Math.floor(point.x * scale / CELL_PIXELS);
            const gy = Math.floor(point.y * scale / CELL_PIXELS);
            const key = gx + ":" + gy;

            if (!grouped.has(key)) {
                grouped.set(key, {
                    gx: gx,
                    gy: gy,
                    ids: new Set(),
                    zips: new Set()
                });
            }

            const cell = grouped.get(key);

            // 同一案件在同一网格中出现多次，仍然只计一次
            for (const id of point.ids) {
                cell.ids.add(id);
            }

            for (const zip of point.zips) {
                cell.zips.add(zip);
            }
        }

        cells = [];

        for (const cell of grouped.values()) {
            cells.push({
                bounds: makeBounds(cell.gx, cell.gy, zoom),
                count: cell.ids.size,
                zips: Array.from(cell.zips).sort()
            });
        }

        activeZoom = zoom;
    }

    function formatDistance(meters) {
        return meters >= 1000
            ? (meters / 1000).toFixed(1) + " km"
            : Math.round(meters) + " m";
    }

    function tooltipContent(cell) {
        const knownZIPs = cell.zips.filter(function (zip) {
            return /^\d{5}$/.test(zip);
        });

        const hasUnknown = cell.zips.includes("Unknown");
        let zipText;

        if (knownZIPs.length === 0) {
            zipText = "Not available";
        } else {
            const displayed = knownZIPs.slice(0, 8);
            zipText = displayed.join(", ");

            if (knownZIPs.length > displayed.length) {
                zipText += " (+" +
                    (knownZIPs.length - displayed.length) +
                    " more)";
            }

            if (hasUnknown) {
                zipText += " · some records have no ZIP";
            }
        }

        const width = map.distance(
            cell.bounds.getNorthWest(),
            cell.bounds.getNorthEast()
        );

        const height = map.distance(
            cell.bounds.getNorthWest(),
            cell.bounds.getSouthWest()
        );

        return (
            "<b>Selected grid area</b><br>" +
            '<span class="count">' +
            cell.count.toLocaleString("en-US") +
            "</span> distinct incidents<br>" +
            "<b>ZIPs in records:</b> " + zipText + "<br>" +
            "<b>Approx. area size:</b> " +
            formatDistance(width) + " × " +
            formatDistance(height) +
            '<div class="note">' +
            "Count applies to this grid, not entire ZIP areas." +
            "</div>"
        );
    }

    function drawVisibleCells() {
        areaLayer.clearLayers();

        const visibleBounds = map.getBounds().pad(0.15);

        for (const cell of cells) {
            if (!visibleBounds.intersects(cell.bounds)) {
                continue;
            }

            const rectangle = L.rectangle(cell.bounds, {
                pane: "areaPane",
                renderer: areaRenderer,
                color: "#475569",
                weight: 0.6,
                opacity: 0.14,
                fill: true,
                fillColor: "#ffffff",
                fillOpacity: 0,
                interactive: true
            });

            rectangle.bindTooltip(
                function () {
                    return tooltipContent(cell);
                },
                {
                    sticky: true,
                    direction: "auto",
                    className: "area-tooltip",
                    opacity: 0.98
                }
            );

            rectangle.on("mouseover", function () {
                rectangle.setStyle({
                    color: "#334155",
                    weight: 2,
                    opacity: 0.9
                });
            });

            rectangle.on("mouseout", function () {
                rectangle.setStyle({
                    color: "#475569",
                    weight: 0.6,
                    opacity: 0.14
                });
            });

            // 手机或触控设备可点击查看
            rectangle.on("click", function (event) {
                rectangle.openTooltip(event.latlng);
            });

            rectangle.addTo(areaLayer);
        }

        const center = map.getCenter();
        const centerPixel = map.project(center, activeZoom);
        const cellWidth = map.distance(
            center,
            map.unproject(
                [centerPixel.x + CELL_PIXELS, centerPixel.y],
                activeZoom
            )
        );

        infoElement.innerHTML =
            "<b>Dynamic area counts</b><br>" +
            "Zoom level: " + activeZoom + "<br>" +
            "Grid width near map center: ≈ " +
            formatDistance(cellWidth) + "<br>" +
            "Zoom in: smaller areas<br>" +
            "Zoom out: larger areas";
    }

    function refresh() {
        const zoom = Math.round(map.getZoom());

        if (zoom !== activeZoom) {
            rebuildAggregation(zoom);

            // 避免缩小时因默认缩放衰减导致热力图过淡
            heat.setOptions({maxZoom: zoom});
        }

        // 平移只更新可见网格，不改变统计范围和计数
        drawVisibleCells();
    }

    map.on("zoomstart", function () {
        // 缩放动画期间移除旧网格，避免提示沿用旧范围
        areaLayer.clearLayers();
    });

    map.on("moveend", refresh);

    refresh();

    // 适应 Streamlit 页面宽度
    if (window.ResizeObserver) {
        const observer = new ResizeObserver(function () {
            map.invalidateSize({pan: false});
        });
        observer.observe(document.getElementById("map"));
    }
})();
</script>
</body>
</html>
"""

components.html(
    map_html.replace("__CRIME_PAYLOAD__", payload_json),
    height=715,
    scrolling=False,
)


# ============================================================
# 统计口径说明
# ============================================================
st.caption(
    "Grid areas automatically split when zooming in and merge "
    "when zooming out. Counts use distinct Incident IDs within "
    "each complete grid area under the selected filters."
)

st.caption(
    "ZIP labels come from incident records within the grid. "
    "They are not ZIP boundaries or whole-ZIP totals. "
    "Panning does not change a grid's count."
)

st.caption(
    "Heatmap colors show smoothed relative density, while hover "
    "counts describe the outlined grid. An incident recorded "
    "in multiple grids may appear once in each, so grid counts "
    "should not be summed as a countywide distinct total."
)
