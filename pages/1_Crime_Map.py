import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data_service import load_and_clean_data
from ui import setup_page, load_with_message, source_caption


# 设置页面并加载在线数据 / Configure the page and load online data.
setup_page("Crime Map", "🗺️")

st.write(
    "Explore crime density. Hover over the map "
    "to see nearby incident counts."
)

df = load_with_message(load_and_clean_data)
source_caption(df)

if df.empty:
    st.warning("No crime records are available.")
    st.stop()


# 创建犯罪大类筛选器 / Create the main crime category filter.
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


# 根据犯罪大类更新子类选项 / Update subcategory options from the main category.
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


# 获取有效日期范围 / Get the valid date range.
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


# 创建包含结束小时的时间筛选器 / Create an hour filter that includes the ending hour.
start_hour, end_hour = st.sidebar.slider(
    "Hour of Day",
    min_value=0,
    max_value=23,
    value=(0, 23),
    step=1,
)


# 应用犯罪类别筛选 / Apply the crime category filters.
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


# 检查是否选择完整日期范围 / Check that a complete date range is selected.
if (
    not isinstance(selected_date_range, (tuple, list))
    or len(selected_date_range) != 2
):
    st.info("Select both the start and end dates.")
    st.stop()

start_date, end_date = selected_date_range


# 应用日期和小时筛选并包含结束日全天 / Apply date and hour filters including the full ending day.
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


# 保留具有有效地图坐标的记录 / Keep records with valid map coordinates.
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


# 同一案件在同一坐标只保留一次 / Keep each incident only once at each coordinate.
mapped = mapped.drop_duplicates(
    subset=["Incident ID", "Latitude", "Longitude"]
)


# 计算事件总数和地图覆盖率 / Calculate distinct incidents and map coverage.
distinct_incidents = filtered_df["Incident ID"].nunique()
mappable_incidents = mapped["Incident ID"].nunique()

map_coverage = (
    mappable_incidents / distinct_incidents * 100
    if distinct_incidents > 0
    else 0
)

col1, col2, col3 = st.columns(3)

col1.metric(
    "Distinct Incidents",
    f"{distinct_incidents:,}",
)

col2.metric(
    "Mappable Incidents",
    f"{mappable_incidents:,}",
)

col3.metric(
    "Map Coverage",
    f"{map_coverage:.1f}%",
)

st.divider()

if mapped.empty:
    st.warning(
        "No mappable incidents match the selected filters."
    )
    st.stop()


# 将案件编号编码为整数以支持浏览器内去重 / Encode incident IDs as integers for browser-side deduplication.
mapped["Incident_Key"] = pd.factorize(
    mapped["Incident ID"],
    sort=False,
)[0]


# 按精确坐标汇总不同案件编号 / Group distinct incident identifiers by exact coordinates.
locations = (
    mapped.groupby(
        ["Latitude", "Longitude"],
        observed=True,
    )["Incident_Key"]
    .agg(
        lambda values: [
            int(value) for value in pd.unique(values)
        ]
    )
    .reset_index()
)


# 在内存中构造地图数据而不创建本地快照 / Build map data in memory without creating local snapshots.
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


# 创建浅灰底图和高对比度热力图 / Create a light-gray basemap and a high-contrast heatmap.
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
        background: #ffffff;
        border-radius: 10px;
    }

    .leaflet-tile-pane {
        filter: grayscale(1) saturate(0) brightness(1.08);
        opacity: 0.65;
    }

    .leaflet-heatmap-layer {
        pointer-events: none !important;
    }

    .crime-tooltip {
        background: #202938;
        color: white;
        border: none;
        border-radius: 7px;
        padding: 10px 14px;
        font-size: 14px;
        pointer-events: none !important;
    }

    .map-legend {
        background: rgba(255, 255, 255, 0.96);
        padding: 10px 13px;
        border-radius: 7px;
        color: #334155;
        font-size: 12px;
        box-shadow: 0 1px 6px rgba(0, 0, 0, 0.15);
    }

    .legend-gradient {
        width: 200px;
        height: 13px;
        margin: 7px 0;
        border-radius: 4px;
        background: linear-gradient(
            to right,
            #ffffb2,
            #fec44f,
            #fe9929,
            #ef3b2c,
            #bd0026,
            #67001f
        );
    }

    .legend-labels {
        display: flex;
        justify-content: space-between;
    }

    #map-message {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 1000;
        max-width: 260px;
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
<div id="map-message">Preparing hover counts…</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>

<script>
(function () {
    "use strict";

    const rows = __CRIME_PAYLOAD__;
    const mapElement = document.getElementById("map");
    const messageElement = document.getElementById("map-message");

    if (!window.L || !L.heatLayer) {
        messageElement.textContent =
            "Map libraries could not load. Check your connection and refresh.";
        return;
    }

    const map = L.map("map", {
        center: [39.13, -77.20],
        zoom: 10,
        minZoom: 7,
        maxZoom: 19,
        zoomControl: true,
        scrollWheelZoom: true,
        doubleClickZoom: true,
        touchZoom: true,
        dragging: true,
        zoomSnap: 1,
        zoomDelta: 1,
        zoomAnimation: false,
        fadeAnimation: false
    });

    L.tileLayer(
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            maxZoom: 19,
            attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright">' +
                'OpenStreetMap</a> contributors'
        }
    ).addTo(map);

    L.control.scale({
        imperial: false,
        position: "bottomleft"
    }).addTo(map);

    const heatPoints = [];
    const queryPoints = [];

    for (const row of rows) {
        const count = row[2].length;

        heatPoints.push([row[0], row[1], count]);

        const point = map.project([row[0], row[1]], 0);

        queryPoints.push({
            x: point.x,
            y: point.y,
            ids: row[2]
        });
    }

    const sortedWeights = heatPoints
        .map(function (point) {
            return point[2];
        })
        .sort(function (a, b) {
            return a - b;
        });

    const referenceIndex = Math.min(
        sortedWeights.length - 1,
        Math.floor((sortedWeights.length - 1) * 0.98)
    );

    const colorReference = Math.max(
        1,
        sortedWeights[referenceIndex]
    );

    const heat = L.heatLayer(heatPoints, {
        radius: 16,
        blur: 12,
        minOpacity: 0.12,
        max: colorReference,
        maxZoom: map.getZoom(),
        gradient: {
            0.05: "#ffffb2",
            0.25: "#fec44f",
            0.45: "#fe9929",
            0.65: "#ef3b2c",
            0.82: "#bd0026",
            1.00: "#67001f"
        }
    }).addTo(map);

    const legend = L.control({
        position: "bottomright"
    });

    legend.onAdd = function () {
        const div = L.DomUtil.create("div", "map-legend");

        div.innerHTML =
            "<b>Relative crime density</b>" +
            '<div class="legend-gradient"></div>' +
            '<div class="legend-labels">' +
            "<span>Low</span><span>High</span></div>";

        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);

        return div;
    };

    legend.addTo(map);

    const workerSource = `
        let points = [];

        function lowerBound(value) {
            let left = 0;
            let right = points.length;

            while (left < right) {
                const middle = (left + right) >>> 1;

                if (points[middle].x < value) {
                    left = middle + 1;
                } else {
                    right = middle;
                }
            }

            return left;
        }

        self.onmessage = function (event) {
            const message = event.data;

            if (message.type === "init") {
                points = message.points;

                points.sort(function (a, b) {
                    return a.x - b.x;
                });

                self.postMessage({type: "ready"});
                return;
            }

            if (message.type !== "query") {
                return;
            }

            const x = message.x;
            const y = message.y;
            const radius = message.radius;
            const radiusSquared = radius * radius;
            const rightEdge = x + radius;
            const ids = new Set();

            let index = lowerBound(x - radius);

            for (; index < points.length; index++) {
                const point = points[index];

                if (point.x > rightEdge) {
                    break;
                }

                const dx = point.x - x;
                const dy = point.y - y;

                if (dx * dx + dy * dy <= radiusSquared) {
                    for (const id of point.ids) {
                        ids.add(id);
                    }
                }
            }

            self.postMessage({
                type: "result",
                token: message.token,
                count: ids.size
            });
        };
    `;

    let worker = null;
    let workerURL = null;
    let workerReady = false;
    let queryInFlight = false;
    let pendingQuery = null;

    let moving = false;
    let mouseInside = false;
    let queryToken = 0;
    let timer = null;
    let hoverPosition = null;

    const HOVER_RADIUS_PIXELS = 18;

    const tooltip = L.tooltip({
        direction: "top",
        offset: [0, -8],
        className: "crime-tooltip",
        opacity: 0.98,
        interactive: false
    });

    function sendPendingQuery() {
        if (
            !workerReady ||
            queryInFlight ||
            !pendingQuery ||
            moving ||
            !mouseInside
        ) {
            return;
        }

        queryInFlight = true;
        worker.postMessage(pendingQuery);
        pendingQuery = null;
    }

    function cancelHover() {
        queryToken += 1;
        clearTimeout(timer);
        pendingQuery = null;
        tooltip.remove();
    }

    function showWorkerError() {
        workerReady = false;
        queryInFlight = false;
        pendingQuery = null;
        tooltip.remove();

        messageElement.style.display = "block";
        messageElement.textContent =
            "Hover counting is unavailable. Refresh the page to retry.";

        if (worker) {
            worker.terminate();
        }

        if (workerURL) {
            URL.revokeObjectURL(workerURL);
            workerURL = null;
        }
    }

    try {
        const blob = new Blob(
            [workerSource],
            {type: "text/javascript"}
        );

        workerURL = URL.createObjectURL(blob);
        worker = new Worker(workerURL);

        worker.onmessage = function (event) {
            const message = event.data;

            if (message.type === "ready") {
                workerReady = true;
                messageElement.style.display = "none";

                if (workerURL) {
                    URL.revokeObjectURL(workerURL);
                    workerURL = null;
                }

                sendPendingQuery();
                return;
            }

            if (message.type !== "result") {
                return;
            }

            queryInFlight = false;

            if (
                message.token === queryToken &&
                mouseInside &&
                !moving &&
                hoverPosition
            ) {
                tooltip
                    .setLatLng(hoverPosition)
                    .setContent(
                        "Distinct incidents: <b>" +
                        message.count.toLocaleString("en-US") +
                        "</b>"
                    )
                    .addTo(map);
            }

            sendPendingQuery();
        };

        worker.onerror = showWorkerError;

        worker.postMessage({
            type: "init",
            points: queryPoints
        });

    } catch (error) {
        showWorkerError();
        console.error(error);
    }

    function prepareQuery(position, token) {
        const projected = map.project(position, 0);

        pendingQuery = {
            type: "query",
            token: token,
            x: projected.x,
            y: projected.y,
            radius:
                HOVER_RADIUS_PIXELS /
                Math.pow(2, map.getZoom())
        };

        sendPendingQuery();
    }

    map.on("mousemove", function (event) {
        mouseInside = true;

        if (moving) {
            return;
        }

        cancelHover();
        hoverPosition = event.latlng;

        const token = queryToken;
        const position = event.latlng;

        timer = setTimeout(function () {
            if (
                moving ||
                !mouseInside ||
                token !== queryToken
            ) {
                return;
            }

            prepareQuery(position, token);
        }, 120);
    });

    map.on("click", function (event) {
        if (moving) {
            return;
        }

        mouseInside = true;
        cancelHover();
        hoverPosition = event.latlng;

        prepareQuery(event.latlng, queryToken);
    });

    mapElement.addEventListener("mouseleave", function () {
        mouseInside = false;
        cancelHover();
    });

    map.on("movestart zoomstart", function () {
        moving = true;
        cancelHover();
    });

    map.on("moveend", function () {
        moving = false;
    });

    map.on("zoomend", function () {
        moving = false;

        heat.setOptions({
            maxZoom: map.getZoom()
        });
    });

    window.addEventListener("resize", function () {
        map.invalidateSize({pan: false});
    });

    window.addEventListener("pagehide", function () {
        if (worker) {
            worker.terminate();
        }

        if (workerURL) {
            URL.revokeObjectURL(workerURL);
        }
    });
})();
</script>
</body>
</html>
"""


# 将地图嵌入页面并保持犯罪数据仅在内存中处理 / Embed the map while keeping crime data processing in memory.
components.html(
    map_html.replace("__CRIME_PAYLOAD__", payload_json),
    height=715,
    scrolling=False,
)


# 说明悬停计数随缩放变化的统计范围 / Explain how the hover counting area changes with zoom.
st.caption(
    "Hover counts show distinct incidents within 18 screen pixels "
    "of the pointer. Zooming out expands the geographic area counted; "
    "zooming in narrows it. Counts follow the selected filters."
)


# 区分热力颜色和附近案件数量 / Distinguish heatmap colors from nearby incident counts.
st.caption(
    "Heatmap colors show smoothed relative density. "
    "The hover count is a local neighborhood total, "
    "not the total for an entire colored hotspot."
)


# 说明增强色彩对比不会改变真实计数 / Explain that enhanced color contrast does not change actual counts.
st.caption(
    "Color intensity uses the 98th percentile of per-location "
    "incident counts as a reference to improve contrast. "
    "High intensities saturate at the darkest color. "
    "Hover counts remain unchanged."
)
