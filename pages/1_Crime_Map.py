import json

import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

from data_service import load_and_clean_data
from ui import setup_page, load_with_message, source_caption


# 设置页面并加载数据 / Set up the page and load data.
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


# 设置犯罪类别筛选 / Configure crime category filters.
st.sidebar.header("Map Filters")

crime_name1_options = ["All"] + sorted(
    df["Crime Name1"].dropna().astype(str).unique().tolist()
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


# 筛选日期时包含结束当天 / Include the entire final day in date filtering.
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


# 保留有效坐标并去除重复案件位置 / Keep valid coordinates and deduplicate incident locations.
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


# 显示案件数量与地图覆盖率 / Display incident totals and map coverage.
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


# 使用整数编号在悬停统计中识别重复案件 / Use integer identifiers to deduplicate hover counts.
map_df["Incident_Key"] = pd.factorize(
    map_df["Incident ID"],
    sort=False,
)[0]


# 合并相同坐标并保留案件编号 / Group identical coordinates while retaining incident identifiers.
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


# 读取与最初代码相同的浅色底图配置 / Read the same light basemap configuration as the original code.
original_map_style = pdk.Deck(
    map_style="light",
).map_style


# 恢复最初的六段热力颜色 / Restore the original six heatmap colors.
original_colors = [
    [255, 255, 178, 255],
    [254, 217, 118, 255],
    [254, 178, 76, 255],
    [253, 141, 60, 255],
    [240, 59, 32, 255],
    [189, 0, 38, 255],
]


# 将地图数据安全地传递给浏览器 / Safely pass map data to the browser.
config_json = json.dumps(
    {
        "points": payload,
        "mapStyle": original_map_style,
        "colors": original_colors,
    },
    ensure_ascii=True,
    allow_nan=False,
    separators=(",", ":"),
).replace("<", "\\u003c")


# 绘制原始热力图并在后台计算悬停案件数 / Render the original heatmap and calculate hover counts in a worker.
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

        #map {
            position: relative;
            width: 100%;
            height: 700px;
            overflow: hidden;
            border-radius: 8px;
            background: #f5f5f5;
        }

        #tooltip {
            position: absolute;
            display: none;
            z-index: 20;
            pointer-events: none;
            padding: 10px 13px;
            border-radius: 6px;
            background: rgba(30, 30, 30, 0.94);
            color: white;
            font-size: 14px;
            white-space: nowrap;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
        }

        #status {
            position: absolute;
            top: 12px;
            left: 12px;
            z-index: 25;
            max-width: 80%;
            padding: 8px 12px;
            border-radius: 5px;
            background: rgba(255, 255, 255, 0.95);
            color: #444;
            font-size: 13px;
            pointer-events: none;
        }
    </style>
</head>

<body>
    <div id="map">
        <div id="tooltip"></div>
        <div id="status">Preparing map...</div>
    </div>

    <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
    <script src="https://unpkg.com/deck.gl@8.9.36/dist.min.js"></script>

    <script>
    (() => {
        const config = __CONFIG__;
        const container = document.getElementById("map");
        const tooltip = document.getElementById("tooltip");
        const status = document.getElementById("status");

        if (!window.deck || !window.maplibregl) {
            status.textContent =
                "Map libraries could not load. Check your internet connection.";
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
                    const radiusSquared = radius * radius;
                    const incidents = new Set();
                    let index = lowerBound(xy[0] - radius);

                    while (
                        index < points.length
                        && points[index].x <= xy[0] + radius
                    ) {
                        const point = points[index];
                        const dx = point.x - xy[0];
                        const dy = point.y - xy[1];

                        if (dx * dx + dy * dy <= radiusSquared) {
                            for (const id of point.ids) {
                                incidents.add(id);
                            }
                        }

                        index += 1;
                    }

                    self.postMessage({
                        type: "result",
                        token: data.token,
                        count: incidents.size,
                        screenX: data.screenX,
                        screenY: data.screenY
                    });
                }
            };
        `;

        let worker;
        let workerURL;
        let ready = false;
        let busy = false;
        let pending = null;
        let timer = null;
        let token = 0;
        let dragging = false;
        let viewer;

        function hideTooltip() {
            token += 1;
            pending = null;
            clearTimeout(timer);
            tooltip.style.display = "none";
        }

        function dispatchQuery() {
            if (!ready || busy || !pending) {
                return;
            }

            const query = pending;
            pending = null;
            busy = true;
            worker.postMessage(query);
        }

        function workerFailure() {
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

            status.style.display = "block";
            status.textContent =
                "Hover counts could not initialize. Refresh the page.";
        }

        try {
            workerURL = URL.createObjectURL(
                new Blob([workerSource], {type: "text/javascript"})
            );

            worker = new Worker(workerURL);
            worker.onerror = workerFailure;

            worker.onmessage = ({data}) => {
                if (data.type === "ready") {
                    ready = true;
                    status.style.display = "none";

                    URL.revokeObjectURL(workerURL);
                    workerURL = null;
                    dispatchQuery();
                    return;
                }

                if (data.type === "result") {
                    busy = false;

                    if (data.token === token && !dragging) {
                        tooltip.textContent =
                            "Distinct incidents: "
                            + data.count.toLocaleString("en-US");

                        tooltip.style.display = "block";

                        const left = Math.max(
                            8,
                            Math.min(
                                data.screenX + 14,
                                container.clientWidth
                                    - tooltip.offsetWidth - 8
                            )
                        );

                        const top = Math.max(
                            8,
                            Math.min(
                                data.screenY + 14,
                                container.clientHeight
                                    - tooltip.offsetHeight - 8
                            )
                        );

                        tooltip.style.left = left + "px";
                        tooltip.style.top = top + "px";
                    }

                    dispatchQuery();
                }
            };

            worker.postMessage({
                type: "init",
                points: config.points
            });
        } catch (error) {
            workerFailure();
        }

        try {
            viewer = new deck.DeckGL({
                container: "map",
                map: maplibregl,
                mapStyle: config.mapStyle,
                mapOptions: {
                    attributionControl: true
                },
                initialViewState: {
                    latitude: 39.13,
                    longitude: -77.20,
                    zoom: 9.4,
                    pitch: 0,
                    bearing: 0,
                    minZoom: 5,
                    maxZoom: 19
                },
                controller: {
                    scrollZoom: true,
                    dragPan: true,
                    dragRotate: false,
                    touchZoom: true,
                    touchRotate: false,
                    doubleClickZoom: true,
                    keyboard: true
                },
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
                onViewStateChange: () => {
                    hideTooltip();
                },
                onError: error => {
                    status.style.display = "block";
                    status.textContent =
                        "Map rendering failed. Refresh or check WebGL support.";
                    console.error(error);
                }
            });
        } catch (error) {
            status.style.display = "block";
            status.textContent =
                "Map could not initialize. Check your browser and connection.";
            return;
        }

        function scheduleQuery(event) {
            hideTooltip();

            if (!ready || dragging || event.buttons) {
                return;
            }

            const bounds = container.getBoundingClientRect();
            const screenX = event.clientX - bounds.left;
            const screenY = event.clientY - bounds.top;
            const currentToken = token;

            timer = setTimeout(() => {
                if (currentToken !== token || dragging) {
                    return;
                }

                const viewport = viewer.getViewports()[0];

                if (!viewport) {
                    return;
                }

                const coordinate = viewport.unproject([
                    screenX,
                    screenY
                ]);

                pending = {
                    type: "query",
                    token: currentToken,
                    lng: coordinate[0],
                    lat: coordinate[1],
                    radius: 18 / (512 * Math.pow(2, viewport.zoom)),
                    screenX,
                    screenY
                };

                dispatchQuery();
            }, 100);
        }

        container.addEventListener("pointermove", scheduleQuery);

        container.addEventListener("pointerdown", () => {
            dragging = true;
            hideTooltip();
        });

        window.addEventListener("pointerup", () => {
            dragging = false;
        });

        window.addEventListener("pointercancel", () => {
            dragging = false;
            hideTooltip();
        });

        container.addEventListener("pointerleave", hideTooltip);
        container.addEventListener("wheel", hideTooltip, {passive: true});

        window.addEventListener("pagehide", () => {
            clearTimeout(timer);

            if (worker) {
                worker.terminate();
            }

            if (workerURL) {
                URL.revokeObjectURL(workerURL);
            }

            if (viewer) {
                viewer.finalize();
            }
        });
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


# 解释热力颜色与悬停数量的含义 / Explain heatmap colors and hover counts.
st.caption(
    "Colors show relative crime density. "
    "Hover counts show distinct incidents within 18 screen pixels "
    "of the cursor; this covers a larger geographic area when zoomed out. "
    "Repeated offense rows for the same incident at the same location "
    "are counted only once."
)
