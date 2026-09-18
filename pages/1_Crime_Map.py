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


# 保留可用于地图的有效坐标 / Keep valid coordinates for mapping.
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
]


# 删除同一案件在相同位置的重复记录 / Remove duplicate records for the same incident at the same location.
map_df = map_df.drop_duplicates(
    subset=["Incident ID", "Latitude", "Longitude"]
)


# 显示案件总数和地图覆盖率 / Display incident totals and map coverage.
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


# 为案件生成用于去重统计的整数编号 / Generate integer identifiers for distinct incident counting.
map_df["Incident_Key"] = pd.factorize(
    map_df["Incident ID"],
    sort=False,
)[0]


# 合并相同坐标并保留对应案件编号 / Group identical coordinates and retain their incident identifiers.
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


# 恢复最初的热力颜色 / Restore the original heatmap colors.
colors = [
    [255, 255, 178, 255],
    [254, 217, 118, 255],
    [254, 178, 76, 255],
    [253, 141, 60, 255],
    [240, 59, 32, 255],
    [189, 0, 38, 255],
]


# 安全地序列化地图配置 / Safely serialize the map configuration.
config_json = json.dumps(
    {
        "points": payload,
        "colors": colors,
        "mapStyle": (
            "https://basemaps.cartocdn.com/"
            "gl/positron-gl-style/style.json"
        ),
    },
    ensure_ascii=True,
    allow_nan=False,
    separators=(",", ":"),
).replace("<", "\\u003c")


# 独立加载底图并同步热力图与悬停统计 / Load the basemap independently and synchronize the heatmap and hover counts.
map_html = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <link
        rel="stylesheet"
        href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"
    >

    <style>
        html, body {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            font-family: Arial, sans-serif;
        }

        #wrapper {
            position: relative;
            width: 100%;
            height: 700px;
            overflow: hidden;
            border-radius: 8px;
            background: #f5f5f5;
        }

        #basemap {
            position: absolute;
            inset: 0;
        }

        #heatmap {
            position: absolute;
            inset: 0;
            pointer-events: none;
            z-index: 2;
        }

        #heatmap canvas {
            pointer-events: none !important;
        }

        .maplibregl-control-container {
            position: relative;
            z-index: 5;
        }

        #tooltip {
            position: absolute;
            display: none;
            pointer-events: none;
            z-index: 10;
            padding: 10px 13px;
            border-radius: 6px;
            background: rgba(30, 30, 30, 0.94);
            color: white;
            font-size: 14px;
            white-space: nowrap;
        }

        #status {
            position: absolute;
            top: 12px;
            left: 12px;
            z-index: 15;
            max-width: 75%;
            padding: 8px 12px;
            border-radius: 5px;
            background: rgba(255, 255, 255, 0.96);
            color: #444;
            font-size: 13px;
            pointer-events: none;
        }
    </style>
</head>

<body>
    <div id="wrapper">
        <div id="basemap"></div>
        <div id="heatmap"></div>
        <div id="tooltip"></div>
        <div id="status">Loading background map...</div>
    </div>

    <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
    <script src="https://unpkg.com/deck.gl@8.9.36/dist.min.js"></script>

    <script>
    (() => {
        const config = __CONFIG__;
        const wrapper = document.getElementById("wrapper");
        const tooltip = document.getElementById("tooltip");
        const status = document.getElementById("status");

        if (!window.maplibregl || !window.deck) {
            status.textContent =
                "Map libraries failed to load. Check your internet connection.";
            return;
        }

        let map;
        let heat;
        let worker;
        let workerURL;
        let ready = false;
        let busy = false;
        let pending = null;
        let timer = null;
        let token = 0;
        let mapLoaded = false;
        let basemapError = false;
        let hoverError = false;
        let heatError = false;

        function updateStatus() {
            const messages = [];

            if (basemapError) {
                messages.push(
                    "Background map could not load. Check your connection and refresh."
                );
            } else if (!mapLoaded) {
                messages.push("Loading background map...");
            }

            if (heatError) {
                messages.push("Heatmap could not render.");
            }

            if (hoverError) {
                messages.push("Hover counts are unavailable.");
            } else if (!ready) {
                messages.push("Preparing hover counts...");
            }

            status.textContent = messages.join(" ");
            status.style.display = messages.length ? "block" : "none";
        }

        function hideTooltip() {
            token += 1;
            pending = null;
            clearTimeout(timer);
            tooltip.style.display = "none";
        }

        function viewState() {
            const center = map.getCenter();

            return {
                longitude: center.lng,
                latitude: center.lat,
                zoom: map.getZoom(),
                pitch: 0,
                bearing: 0
            };
        }

        try {
            map = new maplibregl.Map({
                container: "basemap",
                style: config.mapStyle,
                center: [-77.20, 39.13],
                zoom: 9.4,
                minZoom: 5,
                maxZoom: 19,
                pitch: 0,
                bearing: 0,
                maxPitch: 0,
                dragRotate: false,
                pitchWithRotate: false,
                attributionControl: true,
                renderWorldCopies: false
            });

            map.touchZoomRotate.disableRotation();
            map.keyboard.disableRotation();

            map.addControl(
                new maplibregl.NavigationControl({
                    showCompass: false,
                    showZoom: true
                }),
                "top-right"
            );

            map.on("load", () => {
                mapLoaded = true;
                basemapError = false;
                updateStatus();
            });

            map.on("error", event => {
                basemapError = true;
                updateStatus();
                console.error("Basemap error:", event.error);
            });

            map.on("idle", () => {
                if (map.isStyleLoaded() && map.areTilesLoaded()) {
                    mapLoaded = true;
                    basemapError = false;
                    updateStatus();
                }
            });

            heat = new deck.Deck({
                parent: document.getElementById("heatmap"),
                width: "100%",
                height: "100%",
                viewState: viewState(),
                controller: false,
                layers: [
                    new deck.HeatmapLayer({
                        id: "crime-heatmap",
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
                    heatError = true;
                    updateStatus();
                    console.error("Heatmap error:", error);
                }
            });

            map.on("move", () => {
                hideTooltip();
                heat.setProps({viewState: viewState()});
            });

            map.on("resize", () => {
                hideTooltip();
                heat.setProps({viewState: viewState()});
            });

        } catch (error) {
            status.textContent =
                "Map initialization failed. Refresh or check browser WebGL support.";
            console.error(error);
            return;
        }

        const workerSource = `
            let points = [];

            function project(lng, lat) {
                const sine = Math.sin(lat * Math.PI / 180);

                return [
                    (lng + 180) / 360,
                    0.5 - Math.log((1 + sine) / (1 - sine))
                        / (4 * Math.PI)
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

                if (data.type === "query") {
                    const xy = project(data.lng, data.lat);
                    const radius = data.radius;
                    const ids = new Set();
                    let index = lowerBound(xy[0] - radius);

                    while (
                        index < points.length
                        && points[index].x <= xy[0] + radius
                    ) {
                        const point = points[index];
                        const dx = point.x - xy[0];
                        const dy = point.y - xy[1];

                        if (dx * dx + dy * dy <= radius * radius) {
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
                }
            };
        `;

        function dispatchQuery() {
            if (!ready || busy || !pending) {
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
            hoverError = true;
            hideTooltip();

            if (worker) {
                worker.terminate();
            }

            if (workerURL) {
                URL.revokeObjectURL(workerURL);
                workerURL = null;
            }

            updateStatus();
            console.error("Hover worker error:", error);
        }

        try {
            workerURL = URL.createObjectURL(
                new Blob([workerSource], {
                    type: "text/javascript"
                })
            );

            worker = new Worker(workerURL);
            worker.onerror = failWorker;

            worker.onmessage = ({data}) => {
                if (data.type === "ready") {
                    ready = true;
                    URL.revokeObjectURL(workerURL);
                    workerURL = null;
                    updateStatus();
                    dispatchQuery();
                    return;
                }

                if (data.type === "result") {
                    busy = false;

                    if (data.token === token && !map.isMoving()) {
                        tooltip.textContent =
                            "Distinct incidents: "
                            + data.count.toLocaleString("en-US");

                        tooltip.style.display = "block";

                        tooltip.style.left = Math.max(
                            8,
                            Math.min(
                                data.x + 14,
                                wrapper.clientWidth
                                    - tooltip.offsetWidth - 8
                            )
                        ) + "px";

                        tooltip.style.top = Math.max(
                            8,
                            Math.min(
                                data.y + 14,
                                wrapper.clientHeight
                                    - tooltip.offsetHeight - 8
                            )
                        ) + "px";
                    }

                    dispatchQuery();
                }
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
                || map.isMoving()
                || event.originalEvent.buttons
            ) {
                return;
            }

            const currentToken = token;
            const point = event.point;
            const coordinate = event.lngLat;

            timer = setTimeout(() => {
                if (currentToken !== token || map.isMoving()) {
                    return;
                }

                pending = {
                    type: "query",
                    token: currentToken,
                    lng: coordinate.lng,
                    lat: coordinate.lat,
                    radius: 18 / (512 * Math.pow(2, map.getZoom())),
                    x: point.x,
                    y: point.y
                };

                dispatchQuery();
            }, 100);
        });

        map.on("movestart", hideTooltip);
        map.on("mouseout", hideTooltip);
        wrapper.addEventListener("pointerleave", hideTooltip);

        const observer = new ResizeObserver(() => {
            map.resize();
        });

        observer.observe(wrapper);

        window.addEventListener("pagehide", () => {
            clearTimeout(timer);
            observer.disconnect();

            if (worker) {
                worker.terminate();
            }

            if (workerURL) {
                URL.revokeObjectURL(workerURL);
            }

            heat.finalize();
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


# 恢复最初位于地图下方的颜色比例尺 / Restore the original color legend below the map.
st.markdown(
    '<div style="display:flex;align-items:center;gap:10px;'
    'margin-top:4px;margin-bottom:10px;">'
    '<span style="font-size:14px;">'
    'Relative crime density: Low'
    '</span>'
    '<div style="width:260px;height:14px;border-radius:4px;'
    'background:linear-gradient(to right,'
    'rgb(255,255,178),'
    'rgb(254,217,118),'
    'rgb(254,178,76),'
    'rgb(253,141,60),'
    'rgb(240,59,32),'
    'rgb(189,0,38));">'
    '</div>'
    '<span style="font-size:14px;">High</span>'
    '</div>',
    unsafe_allow_html=True,
)


# 说明颜色和悬停数量的统计含义 / Explain the meaning of colors and hover counts.
st.caption(
    "Colors show relative crime density. "
    "Hover counts show distinct incidents within 18 screen pixels "
    "of the cursor. This covers a larger geographic area when zoomed out. "
    "Repeated offense rows for the same incident at the same location "
    "are counted only once."
)
