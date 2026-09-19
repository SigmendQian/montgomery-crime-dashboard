import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data_service import load_and_clean_data
from ui import setup_page, load_with_message, source_caption


# 设置页面并加载在线数据 / Set up the page and load online data.
setup_page("Crime Map", "🗺️")

st.write(
    "Explore the spatial distribution of crime incidents "
    "across Montgomery County."
)

df = load_with_message(load_and_clean_data)
source_caption(df)

if df.empty:
    st.warning("No data is available.")
    st.stop()


# 设置主要犯罪类别筛选 / Configure the main crime category filter.
st.sidebar.header("Map Filters")

crime_name1_options = ["All"] + sorted(
    df["Crime Name1"].dropna().astype(str).unique().tolist()
)

selected_crime_name1 = st.sidebar.selectbox(
    "Crime Name1",
    crime_name1_options,
)


# 设置联动犯罪类别筛选 / Configure the linked crime category filter.
if selected_crime_name1 == "All":
    crime_name2_options = ["All"]
else:
    crime_name2_options = ["All"] + sorted(
        df.loc[
            df["Crime Name1"].astype(str) == selected_crime_name1,
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


# 设置日期范围筛选 / Configure the date range filter.
valid_dates = df["Date"].dropna()

if valid_dates.empty:
    st.warning("No valid dates are available.")
    st.stop()

min_date = valid_dates.min().date()
max_date = valid_dates.max().date()

selected_date_range = st.sidebar.date_input(
    "Date Range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)


# 设置小时范围筛选 / Configure the hour range filter.
start_hour, end_hour = st.sidebar.slider(
    "Hour of Day",
    min_value=0,
    max_value=23,
    value=(0, 23),
    step=1,
)


# 应用犯罪类别筛选 / Apply crime category filters.
filtered_df = df

if selected_crime_name1 != "All":
    filtered_df = filtered_df.loc[
        filtered_df["Crime Name1"].astype(str)
        == selected_crime_name1
    ]

if selected_crime_name2 != "All":
    filtered_df = filtered_df.loc[
        filtered_df["Crime Name2"].astype(str)
        == selected_crime_name2
    ]


# 应用日期与小时筛选并包含结束当天 / Apply date and hour filters including the entire final day.
if (
    not isinstance(selected_date_range, (tuple, list))
    or len(selected_date_range) != 2
):
    st.info("Select both the start and end dates.")
    st.stop()

start_date, end_date = selected_date_range

filtered_df = filtered_df.loc[
    (filtered_df["Date"] >= pd.Timestamp(start_date))
    & (
        filtered_df["Date"]
        < pd.Timestamp(end_date) + pd.Timedelta(days=1)
    )
    & filtered_df["Hour"].between(start_hour, end_hour)
]

st.caption(
    f"Selected hours: "
    f"{start_hour:02d}:00–{end_hour:02d}:59 (inclusive)."
)


# 保留有效案件坐标 / Keep valid incident coordinates.
map_df = filtered_df.loc[
    filtered_df["Valid_Coordinates"].fillna(False),
    ["Incident ID", "Latitude", "Longitude"],
].copy()

for column in ["Latitude", "Longitude"]:
    map_df[column] = pd.to_numeric(
        map_df[column],
        errors="coerce",
    )

map_df = map_df.dropna(
    subset=["Incident ID", "Latitude", "Longitude"]
)

map_df = map_df.loc[
    map_df["Latitude"].between(-85.05112878, 85.05112878)
    & map_df["Longitude"].between(-180, 180)
].drop_duplicates(
    subset=["Incident ID", "Latitude", "Longitude"]
)


# 显示案件总数与地图覆盖率 / Display incident totals and map coverage.
distinct_incidents = filtered_df["Incident ID"].nunique()
mappable_incidents = map_df["Incident ID"].nunique()

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

if map_df.empty:
    st.warning("No mappable incidents match the selected filters.")
    st.stop()


# 为案件建立用于去重统计的整数编号 / Assign integer identifiers for distinct incident counting.
map_df["Incident_Key"] = pd.factorize(
    map_df["Incident ID"],
    sort=False,
)[0]


# 合并相同位置并保留案件编号 / Group identical locations and retain incident identifiers.
locations = (
    map_df.groupby(
        ["Latitude", "Longitude"],
        sort=False,
    )["Incident_Key"]
    .agg(lambda values: [int(value) for value in pd.unique(values)])
    .reset_index()
)

payload = [
    [
        float(row.Longitude),
        float(row.Latitude),
        row.Incident_Key,
    ]
    for row in locations.itertuples(index=False)
]


# 保留最初的六段热力颜色 / Keep the original six heatmap colors.
colors = [
    [255, 255, 178, 255],
    [254, 217, 118, 255],
    [254, 178, 76, 255],
    [253, 141, 60, 255],
    [240, 59, 32, 255],
    [189, 0, 38, 255],
]


# 安全地传递浏览器地图数据 / Safely pass map data to the browser.
config_json = json.dumps(
    {
        "points": payload,
        "colors": colors,
    },
    ensure_ascii=True,
    allow_nan=False,
    separators=(",", ":"),
).replace("<", "\\u003c")


# 使用图片底图并同步热力图与悬停统计 / Use a raster basemap and synchronize the heatmap and hover counts.
map_html = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="referrer" content="strict-origin-when-cross-origin">

    <link
        rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    >

    <style>
        html, body {
            margin: 0;
            padding: 0;
            width: 100%;
            font-family: Arial, sans-serif;
        }

        #map {
            position: relative;
            width: 100%;
            height: 700px;
            overflow: hidden;
            border-radius: 8px;
            background: #f4f4f4;
        }

        #map .leaflet-tile-pane {
            filter: grayscale(1) brightness(1.05);
        }

        #heat {
            position: absolute;
            inset: 0;
            z-index: 450;
            pointer-events: none;
        }

        #heat canvas {
            pointer-events: none !important;
        }

        #tooltip {
            position: absolute;
            display: none;
            z-index: 1000;
            pointer-events: none;
            padding: 9px 12px;
            border-radius: 6px;
            background: rgba(30, 30, 30, 0.94);
            color: #fff;
            font-size: 14px;
            white-space: nowrap;
        }

        #status {
            position: absolute;
            top: 12px;
            left: 55px;
            z-index: 1000;
            max-width: 70%;
            pointer-events: none;
            padding: 8px 12px;
            border-radius: 5px;
            background: rgba(255, 255, 255, 0.96);
            color: #444;
            font-size: 13px;
        }
    </style>
</head>

<body>
    <div id="map">
        <div id="heat"></div>
        <div id="tooltip"></div>
        <div id="status">Loading map...</div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/deck.gl@8.9.36/dist.min.js"></script>

    <script>
    (() => {
        const config = __CONFIG__;
        const container = document.getElementById("map");
        const tooltip = document.getElementById("tooltip");
        const status = document.getElementById("status");

        if (!window.L || !window.deck) {
            status.textContent =
                "Map libraries could not load. Check your connection.";
            return;
        }

        const messages = {
            tiles: "Loading background map...",
            hover: "Preparing hover counts...",
            heat: ""
        };

        function updateStatus() {
            const text = Object.values(messages).filter(Boolean).join(" ");
            status.textContent = text;
            status.style.display = text ? "block" : "none";
        }

        const map = L.map("map", {
            center: [39.13, -77.20],
            zoom: 10.4,
            minZoom: 6,
            maxZoom: 19,
            zoomSnap: 0.1,
            zoomDelta: 0.5,
            zoomAnimation: false,
            fadeAnimation: false,
            markerZoomAnimation: false,
            scrollWheelZoom: true,
            doubleClickZoom: true,
            touchZoom: true,
            dragging: true,
            inertia: false
        });

        let tilesLoaded = 0;

        const tileTimeout = setTimeout(() => {
            if (tilesLoaded === 0) {
                messages.tiles =
                    "Background map is taking too long to load. Check your connection.";
                updateStatus();
            }
        }, 20000);

        const tiles = L.tileLayer(
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                maxZoom: 19,
                noWrap: true,
                attribution:
                    '&copy; <a href="https://www.openstreetmap.org/copyright" '
                    + 'target="_blank" rel="noopener">'
                    + 'OpenStreetMap</a> contributors'
            }
        );

        tiles.on("tileload", () => {
            tilesLoaded += 1;
            clearTimeout(tileTimeout);
            messages.tiles = "";
            updateStatus();
        });

        tiles.on("tileerror", () => {
            messages.tiles =
                "Some background tiles failed to load. Try refreshing.";
            updateStatus();
        });

        tiles.addTo(map);

        let heat = null;
        let token = 0;
        let timer = null;
        let pending = null;
        let ready = false;
        let busy = false;
        let moving = false;
        let worker = null;
        let workerURL = null;

        function hideTooltip() {
            token += 1;
            pending = null;
            clearTimeout(timer);
            tooltip.style.display = "none";
        }

        function getViewState() {
            const center = map.getCenter();

            return {
                longitude: center.lng,
                latitude: center.lat,
                zoom: map.getZoom() - 1,
                pitch: 0,
                bearing: 0
            };
        }

        try {
            heat = new deck.Deck({
                parent: document.getElementById("heat"),
                width: "100%",
                height: "100%",
                controller: false,
                viewState: getViewState(),
                layers: [
                    new deck.HeatmapLayer({
                        id: "crime-density",
                        data: config.points,
                        getPosition: point => [point[0], point[1]],
                        getWeight: point => point[2].length,
                        aggregation: "SUM",
                        radiusPixels: 35,
                        intensity: 1,
                        threshold: 0.03,
                        colorRange: config.colors,
                        pickable: false
                    })
                ],
                onError: error => {
                    messages.heat =
                        "Heatmap could not render. Check browser WebGL support.";
                    updateStatus();
                    console.error(error);
                }
            });
        } catch (error) {
            messages.heat = "Heatmap initialization failed.";
            updateStatus();
            console.error(error);
        }

        function synchronize() {
            hideTooltip();

            if (heat) {
                heat.setProps({viewState: getViewState()});
            }
        }

        map.on("movestart zoomstart", () => {
            moving = true;
            hideTooltip();
        });

        map.on("move zoom resize", synchronize);

        map.on("moveend zoomend", () => {
            moving = false;
            synchronize();
        });

        const workerSource = `
            let points = [];

            function project(lng, lat) {
                const s = Math.sin(lat * Math.PI / 180);

                return [
                    (lng + 180) / 360,
                    0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)
                ];
            }

            function lowerBound(x) {
                let left = 0;
                let right = points.length;

                while (left < right) {
                    const middle = (left + right) >>> 1;

                    if (points[middle].x < x) {
                        left = middle + 1;
                    } else {
                        right = middle;
                    }
                }

                return left;
            }

            self.onmessage = ({data}) => {
                if (data.type === "init") {
                    points = data.points.map(point => {
                        const xy = project(point[0], point[1]);

                        return {
                            x: xy[0],
                            y: xy[1],
                            ids: point[2]
                        };
                    });

                    points.sort((a, b) => a.x - b.x);
                    self.postMessage({type: "ready"});
                    return;
                }

                const xy = project(data.lng, data.lat);
                const r = data.radius;
                const ids = new Set();
                let index = lowerBound(xy[0] - r);

                while (
                    index < points.length
                    && points[index].x <= xy[0] + r
                ) {
                    const point = points[index];
                    const dx = point.x - xy[0];
                    const dy = point.y - xy[1];

                    if (dx * dx + dy * dy <= r * r) {
                        for (const id of point.ids) {
                            ids.add(id);
                        }
                    }

                    index += 1;
                }

                self.postMessage({
                    type: "result",
                    token: data.token,
                    count: ids.size,
                    x: data.x,
                    y: data.y
                });
            };
        `;

        function dispatchQuery() {
            if (!ready || busy || !pending || moving) {
                return;
            }

            busy = true;
            const query = pending;
            pending = null;
            worker.postMessage(query);
        }

        function failWorker(error) {
            ready = false;
            busy = false;
            hideTooltip();

            if (worker) {
                worker.terminate();
            }

            if (workerURL) {
                URL.revokeObjectURL(workerURL);
                workerURL = null;
            }

            messages.hover = "Hover counts could not initialize.";
            updateStatus();
            console.error(error);
        }

        try {
            workerURL = URL.createObjectURL(
                new Blob([workerSource], {type: "text/javascript"})
            );

            worker = new Worker(workerURL);
            worker.onerror = failWorker;

            worker.onmessage = ({data}) => {
                if (data.type === "ready") {
                    ready = true;
                    URL.revokeObjectURL(workerURL);
                    workerURL = null;
                    messages.hover = "";
                    updateStatus();
                    dispatchQuery();
                    return;
                }

                busy = false;

                if (data.token === token && !moving) {
                    tooltip.textContent =
                        "Distinct incidents: "
                        + data.count.toLocaleString("en-US");

                    tooltip.style.display = "block";

                    tooltip.style.left = Math.max(
                        8,
                        Math.min(
                            data.x + 14,
                            container.clientWidth - tooltip.offsetWidth - 8
                        )
                    ) + "px";

                    tooltip.style.top = Math.max(
                        8,
                        Math.min(
                            data.y + 14,
                            container.clientHeight - tooltip.offsetHeight - 8
                        )
                    ) + "px";
                }

                dispatchQuery();
            };

            worker.postMessage({
                type: "init",
                points: config.points
            });
        } catch (error) {
            failWorker(error);
        }

        map.on("mousemove", event => {
            hideTooltip();

            if (
                !ready
                || moving
                || event.originalEvent.buttons
            ) {
                return;
            }

            const currentToken = token;

            timer = setTimeout(() => {
                if (currentToken !== token || moving) {
                    return;
                }

                pending = {
                    type: "query",
                    token: currentToken,
                    lng: event.latlng.lng,
                    lat: event.latlng.lat,
                    radius: 18 / (256 * Math.pow(2, map.getZoom())),
                    x: event.containerPoint.x,
                    y: event.containerPoint.y
                };

                dispatchQuery();
            }, 100);
        });

        map.on("mouseout", hideTooltip);
        container.addEventListener("pointerleave", hideTooltip);

        const observer = new ResizeObserver(() => {
            map.invalidateSize({pan: false});
            synchronize();
        });

        observer.observe(container);

        window.addEventListener("pagehide", () => {
            clearTimeout(timer);
            clearTimeout(tileTimeout);
            observer.disconnect();

            if (worker) {
                worker.terminate();
            }

            if (workerURL) {
                URL.revokeObjectURL(workerURL);
            }

            if (heat) {
                heat.finalize();
            }

            map.remove();
        });

        updateStatus();
    })();
    </script>
</body>
</html>
"""

components.html(
    map_html.replace("__CONFIG__", config_json),
    height=710,
    scrolling=False,
)


# 保留原来的热力颜色比例尺 / Keep the original heatmap color legend.
st.markdown(
    '<div style="display:flex;align-items:center;gap:10px;'
    'margin-top:4px;margin-bottom:10px;">'
    '<span style="font-size:14px;">Relative crime density: Low</span>'
    '<div style="width:260px;height:14px;border-radius:4px;'
    'background:linear-gradient(to right,'
    'rgb(255,255,178),'
    'rgb(254,217,118),'
    'rgb(254,178,76),'
    'rgb(253,141,60),'
    'rgb(240,59,32),'
    'rgb(189,0,38));"></div>'
    '<span style="font-size:14px;">High</span>'
    '</div>',
    unsafe_allow_html=True,
)


# 说明热力颜色和悬停数量的含义 / Explain heatmap colors and hover counts.
st.caption(
    "Colors show relative crime density. "
    "Hover counts show distinct incidents within 18 screen pixels "
    "of the cursor, covering a larger geographic area when zoomed out. "
    "Repeated offense rows for the same incident at the same location "
    "are counted only once."
)
