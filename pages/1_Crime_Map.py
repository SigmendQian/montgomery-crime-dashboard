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
    "Zoom out to merge nearby incident points. "
    "Zoom in to separate them."
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
# 有效地图记录
# ============================================================
mapped = filtered_df.loc[
    filtered_df["Valid_Coordinates"].fillna(False),
    ["Incident ID", "Latitude", "Longitude"],
].copy()

for column in ["Latitude", "Longitude"]:
    mapped[column] = pd.to_numeric(
        mapped[column],
        errors="coerce",
    )

mapped = mapped.dropna(
    subset=["Incident ID", "Latitude", "Longitude"]
)

mapped = mapped.loc[
    mapped["Latitude"].between(-85.05112878, 85.05112878)
    & mapped["Longitude"].between(-180, 180)
].copy()

# 同一案件在同一坐标只保留一次
mapped = mapped.drop_duplicates(
    subset=["Incident ID", "Latitude", "Longitude"]
)


# ============================================================
# 汇总指标
# ============================================================
distinct_incidents = filtered_df["Incident ID"].nunique()
mappable_incidents = mapped["Incident ID"].nunique()

map_coverage = (
    mappable_incidents / distinct_incidents * 100
    if distinct_incidents > 0
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
# 将案件 ID 编码为整数，用于浏览器内聚合去重
# 不写入本地文件，不创建快照或磁盘缓存
# ============================================================
mapped["Incident_Key"] = pd.factorize(
    mapped["Incident ID"],
    sort=False,
)[0]

locations = (
    mapped.groupby(
        ["Latitude", "Longitude"],
        observed=True,
    )["Incident_Key"]
    .agg(lambda values: [int(v) for v in pd.unique(values)])
    .reset_index()
)

# 每个坐标：[纬度、经度、不同案件编号数组]
payload = [
    [
        float(row.Latitude),
        float(row.Longitude),
        row.Incident_Key,
    ]
    for row in locations.itertuples(index=False)
]

payload_json = json.dumps(
    payload,
    ensure_ascii=True,
    separators=(",", ":"),
    allow_nan=False,
).replace("<", "\\u003c")


# ============================================================
# 动态散点聚合地图
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
<link
    rel="stylesheet"
    href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"
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
        background: #f3f4f6;
        border-radius: 10px;
    }

    .crime-icon {
        background: transparent;
        border: none;
    }

    .crime-bubble {
        width: 100%;
        height: 100%;
        box-sizing: border-box;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 2px solid rgba(255, 255, 255, 0.90);
        box-shadow: 0 2px 7px rgba(0, 0, 0, 0.20);
        font-family: Arial, sans-serif;
        font-weight: bold;
        font-size: 12px;
        white-space: nowrap;
        cursor: pointer;
    }

    .crime-tooltip {
        background: #202938;
        color: white;
        border: none;
        border-radius: 7px;
        padding: 10px 13px;
        font-size: 14px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.20);
    }

    #status {
        position: absolute;
        top: 12px;
        right: 12px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.96);
        color: #334155;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 12px;
        pointer-events: none;
    }
</style>
</head>

<body>
<div id="map"></div>
<div id="status">Loading map…</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>

<script>
(function () {
    "use strict";

    const rows = __CRIME_PAYLOAD__;
    const status = document.getElementById("status");

    if (!window.L || !L.markerClusterGroup) {
        status.textContent =
            "Map libraries could not load. Check your connection and refresh.";
        return;
    }

    const map = L.map("map", {
        center: [39.13, -77.20],
        zoom: 10,
        minZoom: 4,
        maxZoom: 19,
        scrollWheelZoom: true
    });

    // 使用不带地名标签的底图
    L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
        {
            attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright">' +
                'OpenStreetMap</a> contributors &copy; ' +
                '<a href="https://carto.com/attributions">CARTO</a>',
            subdomains: "abcd",
            maxZoom: 20
        }
    ).addTo(map);

    const numberFormat = new Intl.NumberFormat("en-US");

    function countText(count) {
        return numberFormat.format(count);
    }

    // 圆点只显示数量；颜色沿用黄→橙→红
    function makeIcon(count) {
        let size;
        let background;
        let foreground;

        if (count < 10) {
            size = 28;
            background = "#ffffb2";
            foreground = "#4a3418";
        } else if (count < 100) {
            size = 36;
            background = "#fed976";
            foreground = "#4a3418";
        } else if (count < 1000) {
            size = 46;
            background = "#fd8d3c";
            foreground = "#42220b";
        } else if (count < 10000) {
            size = 58;
            background = "#f03b20";
            foreground = "#ffffff";
        } else {
            size = 72;
            background = "#bd0026";
            foreground = "#ffffff";
        }

        return L.divIcon({
            className: "crime-icon",
            html:
                '<div class="crime-bubble" style="' +
                "background:" + background + ";" +
                "color:" + foreground + ';">' +
                countText(count) +
                "</div>",
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2]
        });
    }

    function tooltipText(count) {
        return "Distinct incidents: <b>" + countText(count) + "</b>";
    }

    // 必须统计不同案件 ID，不能直接使用聚合点数量
    function distinctClusterCount(cluster) {
        const ids = new Set();

        for (const marker of cluster.getAllChildMarkers()) {
            for (const id of marker.options.incidentKeys) {
                ids.add(id);
            }
        }

        return ids.size;
    }

    const clusters = L.markerClusterGroup({
        maxClusterRadius: 65,

        // 不显示聚合边界、多边形或网格
        showCoverageOnHover: false,

        // 点击聚合点放大，缩放自动拆分/合并
        zoomToBoundsOnClick: true,
        animate: true,

        // 最深缩放时仍保持圆点，不拉出放射连线
        spiderfyOnMaxZoom: false,

        removeOutsideVisibleBounds: true,
        chunkedLoading: true,
        chunkInterval: 100,
        chunkDelay: 30,

        chunkProgress: function (processed, total) {
            if (processed >= total) {
                status.style.display = "none";
            } else {
                status.textContent =
                    "Loading map… " +
                    Math.round(processed / total * 100) + "%";
            }
        },

        iconCreateFunction: function (cluster) {
            return makeIcon(distinctClusterCount(cluster));
        }
    });

    // 聚合点悬停：只显示犯罪数量
    clusters.on("clustermouseover", function (event) {
        const cluster = event.layer;
        const content = tooltipText(distinctClusterCount(cluster));

        if (cluster.getTooltip()) {
            cluster.setTooltipContent(content);
        } else {
            cluster.bindTooltip(content, {
                direction: "top",
                className: "crime-tooltip",
                opacity: 0.98
            });
        }

        cluster.openTooltip();
    });

    clusters.on("clustermouseout", function (event) {
        event.layer.closeTooltip();
    });

    // 先创建每个实际坐标的圆点
    const markers = rows.map(function (row) {
        const incidentKeys = row[2];
        const count = incidentKeys.length;

        const marker = L.marker([row[0], row[1]], {
            icon: makeIcon(count),
            incidentKeys: incidentKeys,
            keyboard: true,
            alt: countText(count) + " distinct incidents"
        });

        marker.bindTooltip(tooltipText(count), {
            direction: "top",
            className: "crime-tooltip",
            opacity: 0.98
        });

        marker.on("click", function () {
            marker.openTooltip();
        });

        return marker;
    });

    map.addLayer(clusters);
    clusters.addLayers(markers);

    map.on("zoomstart", function () {
        map.closeTooltip();
    });

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

st.caption(
    "Numbers show distinct incidents within each point or cluster. "
    "Nearby points merge when zooming out and separate when zooming in."
)

st.caption(
    "An incident recorded at multiple locations is counted once "
    "within a cluster. If those locations separate into different "
    "clusters, the incident may appear in each; displayed counts "
    "should not be summed as a countywide distinct total."
)
