import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data_service import load_and_clean_data
from ui import setup_page, load_with_message, source_caption


# 设置页面 / Set up the page.
setup_page("Crime Map", "🗺️")


# 加载在线案件数据 / Load online incident data.
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


# 应用日期和小时筛选并包含结束当天 / Apply date and hour filters including the entire final day.
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


# 保留有效坐标并删除重复案件位置 / Keep valid coordinates and remove duplicate incident locations.
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


# 使用整数编号识别同一案件 / Identify each incident with an integer identifier.
map_df["Incident_Key"] = pd.factorize(
    map_df["Incident ID"],
    sort=False,
)[0]


# 合并相同坐标并保留案件编号 / Group identical coordinates and retain incident identifiers.
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


# 保留原始热力颜色并设置悬停范围 / Keep the original heatmap colors and set the hover radius.
config = {
    "points": payload,
    "colors": [
        [255, 255, 178, 255],
        [254, 217, 118, 255],
        [254, 178, 76, 255],
        [253, 141, 60, 255],
        [240, 59, 32, 255],
        [189, 0, 38, 255],
    ],
    "heatRadius": 35,
    "hoverRadius": 18,
}

config_json = json.dumps(
    config,
    ensure_ascii=True,
    allow_nan=False,
    separators=(",", ":"),
).replace("<", "\\u003c")


# 使用 OpenFreeMap 官方样式并仅保留道路与水系 / Use the official OpenFreeMap style and keep only roads and water.
map_html = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <link
        rel="stylesheet"
        href="https://unpkg.com/maplibre-gl@5/dist/maplibre-gl.css"
    >

    <style>
        html, body {
            margin: 0;
            padding: 0;
            width: 100%;
            font-family: Arial, sans-serif;
        }

        #wrapper {
            position: relative;
            width: 100%;
            height: 700px;
            overflow: hidden;
            border-radius: 8px;
            background: #fafafa;
        }

        #basemap {
            position: absolute;
            inset: 0;
        }

        #heat {
            position: absolute;
            inset: 0;
            z-index: 2;
            pointer-events: none;
        }

        #heat canvas {
            pointer-events: none !important;
        }

        .maplibregl-control-container {
            position: relative;
            z-index: 5;
        }

        #tooltip {
            position: absolute;
            display: none;
            z-index: 10;
            pointer-events: none;
            padding: 9px 12px;
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
        <div id="heat"></div>
        <div id="tooltip"></div>
        <div id="status">Loading map...</div>
    </div>

    <script src="https://unpkg.com/maplibre-gl@5/dist/maplibre-gl.js"></script>
    <script src="https://unpkg.com/deck.gl@8.9.36/dist.min.js"></script>

    <script>
    (() => {
        const config = __CONFIG__;
        const wrapper = document.getElementById("wrapper");
        const tooltip = document.getElementById("tooltip");
        const status = document.getElementById("status");

        if (!window.maplibregl || !window.deck) {
            status.textContent =
                "Map libraries failed to load. Check your connection.";
            return;
        }

        const messages = {
            map: "Loading background map...",
            heat: "",
            hover: "Preparing hover counts..."
        };

        function updateStatus() {
            const text = Object.values(messages).filter(Boolean).join(" ");
            status.textContent = text;
            status.style.display = text ? "block" : "none";
        }

        const OPENFREEMAP_STYLE =
            "https://tiles.openfreemap.org/styles/liberty";

        let map;
        let heat;
        let worker;
        let workerURL;
        let observer;
        let mapTimeout;
        let hoverTimeout;
        let timer;
        let token = 0;
        let ready = false;
        let busy = false;
        let pending = null;

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
                zoom: map.getZoom(),
                pitch: 0,
                bearing: 0
            };
        }

        window.addEventListener("pagehide", () => {
            clearTimeout(timer);
            clearTimeout(mapTimeout);
            clearTimeout(hoverTimeout);

            if (observer) observer.disconnect();
            if (worker) worker.terminate();
            if (workerURL) URL.revokeObjectURL(workerURL);
            if (heat) heat.finalize();
            if (map) map.remove();
        });

        try {
            map = new maplibregl.Map({
                container: "basemap",
                style: OPENFREEMAP_STYLE,
                center: [-77.20, 39.13],
                zoom: 9.4,
                minZoom: 5,
                maxZoom: 19,
                pitch: 0,
                maxPitch: 0,
                bearing: 0,
                dragRotate: false,
                pitchWithRotate: false,
                renderWorldCopies: false,
                attributionControl: true
            });

            map.touchZoomRotate.disableRotation();
            map.keyboard.disableRotation();

            map.addControl(
                new maplibregl.NavigationControl({
                    showCompass: false
                }),
                "top-right"
            );

            mapTimeout = setTimeout(() => {
                messages.map =
                    "OpenFreeMap is taking too long to load. Check your connection.";
                updateStatus();
            }, 20000);

            map.on("style.load", () => {
                const style = map.getStyle();
                const layers = style && style.layers ? style.layers : [];

                for (const layer of layers) {
                    const layerId = String(layer.id || "").toLowerCase();
                    const sourceLayer = String(
                        layer["source-layer"] || ""
                    ).toLowerCase();

                    const hideLabels =
                        layer.type === "symbol";

                    const hideBuildings =
                        sourceLayer.includes("building")
                        || layerId.includes("building");

                    const hideLandDetail =
                        sourceLayer.includes("landcover")
                        || sourceLayer.includes("landuse")
                        || sourceLayer.includes("park")
                        || layerId.includes("landcover")
                        || layerId.includes("landuse")
                        || layerId.includes("park");

                    const hideBoundaries =
                        sourceLayer.includes("boundary")
                        || layerId.includes("boundary");

                    if (
                        hideLabels
                        || hideBuildings
                        || hideLandDetail
                        || hideBoundaries
                    ) {
                        try {
                            map.setLayoutProperty(
                                layer.id,
                                "visibility",
                                "none"
                            );
                        } catch (error) {
                            // Ignore layers that do not expose visibility.
                        }
                    }
                }

                clearTimeout(mapTimeout);
                messages.map = "";
                updateStatus();
            });

            map.on("error", event => {
                clearTimeout(mapTimeout);

                const error = event.error || {};
                const code = error.status || error.statusCode;

                const message =
                    error.message
                    ? " " + error.message
                    : "";

                messages.map =
                    "Background map failed to load"
                    + (code ? " (HTTP " + code + ")" : "")
                    + message;

                updateStatus();
            });

            heat = new deck.Deck({
                parent: document.getElementById("heat"),
                width: "100%",
                height: "100%",
                viewState: getViewState(),
                controller: false,
                layers: [
                    new deck.HeatmapLayer({
                        id: "crime-density",
                        data: config.points,
                        getPosition: point => [point[0], point[1]],
                        getWeight: point => point[2].length,
                        aggregation: "SUM",
                        radiusPixels: config.heatRadius,
                        intensity: 1,
                        threshold: 0.03,
                        colorRange: config.colors,
                        pickable: false
                    })
                ],
                onError: () => {
                    messages.heat =
                        "Heatmap rendering failed. Check browser WebGL support.";
                    updateStatus();
                }
            });

            map.on("move", () => {
                hideTooltip();
                heat.setProps({viewState: getViewState()});
            });

            map.on("resize", () => {
                hideTooltip();
                heat.setProps({viewState: getViewState()});
            });

        } catch (error) {
            clearTimeout(mapTimeout);
            messages.map = "Map initialization failed.";
            messages.hover = "";
            updateStatus();
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
            };
        `;

        function dispatchQuery() {
            if (!ready || busy || !pending || map.isMoving()) {
                return;
            }

            busy = true;
            const query = pending;
            pending = null;
            worker.postMessage(query);
        }

        function failWorker() {
            ready = false;
            busy = false;
            hideTooltip();
            clearTimeout(hoverTimeout);

            if (worker) worker.terminate();

            if (workerURL) {
                URL.revokeObjectURL(workerURL);
                workerURL = null;
            }

            messages.hover = "Hover counts could not initialize.";
            updateStatus();
        }

        try {
            workerURL = URL.createObjectURL(
                new Blob([workerSource], {
                    type: "text/javascript"
                })
            );

            worker = new Worker(workerURL);
            worker.onerror = failWorker;
            hoverTimeout = setTimeout(failWorker, 20000);

            worker.onmessage = ({data}) => {
                if (data.type === "ready") {
                    clearTimeout(hoverTimeout);
                    ready = true;
                    messages.hover = "";
                    URL.revokeObjectURL(workerURL);
                    workerURL = null;
                    updateStatus();
                    dispatchQuery();
                    return;
                }

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
                            wrapper.clientWidth - tooltip.offsetWidth - 8
                        )
                    ) + "px";

                    tooltip.style.top = Math.max(
                        8,
                        Math.min(
                            data.y + 14,
                            wrapper.clientHeight - tooltip.offsetHeight - 8
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
            failWorker();
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

            timer = setTimeout(() => {
                if (currentToken !== token || map.isMoving()) {
                    return;
                }

                pending = {
                    type: "query",
                    token: currentToken,
                    lng: event.lngLat.lng,
                    lat: event.lngLat.lat,
                    radius: config.hoverRadius
                        / (512 * Math.pow(2, map.getZoom())),
                    x: event.point.x,
                    y: event.point.y
                };

                dispatchQuery();
            }, 100);
        });

        map.on("movestart", hideTooltip);
        map.on("mouseout", hideTooltip);
        wrapper.addEventListener("pointerleave", hideTooltip);

        observer = new ResizeObserver(() => {
            map.resize();
        });

        observer.observe(wrapper);
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


# 说明热力颜色与悬停数量的含义 / Explain heatmap colors and hover counts.
st.caption(
    "Colors show relative crime density. "
    "Hover counts show distinct incidents within 18 screen pixels "
    "of the cursor, covering a larger geographic area when zoomed out. "
    "Repeated offense rows for the same incident at the same location "
    "are counted only once."
)
