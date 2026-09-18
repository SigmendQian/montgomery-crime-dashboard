import pydeck as pdk
import streamlit as st

import pandas as pd
from data_service import load_and_clean_data
from ui import setup_page, load_with_message, source_caption


# 页面与在线数据 / Page and online data
setup_page("Crime Map", "🗺️")
st.write("Explore the spatial distribution of crime incidents across Montgomery County.")
df = load_with_message(load_and_clean_data)
source_caption(df)

# 侧边栏筛选 / Sidebar filters
st.sidebar.header(
    "Map Filters"
)


# Crime Name1 筛选 / Crime Name1 filter
crime_name1_options = [
    "All"
] + sorted(
    df["Crime Name1"]
    .dropna()
    .astype(str)
    .unique()
    .tolist()
)


selected_crime_name1 = (
    st.sidebar.selectbox(
        "Crime Name1",
        crime_name1_options
    )
)


# Crime Name2 联动筛选 / Linked Crime Name2 filter
if selected_crime_name1 == "All":

    crime_name2_options = [
        "All"
    ]

else:

    crime_name2_options = [
        "All"
    ] + sorted(
        df.loc[
            df["Crime Name1"]
            .astype(str)
            == selected_crime_name1,
            "Crime Name2"
        ]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )


selected_crime_name2 = (
    st.sidebar.selectbox(
        "Crime Name2",
        crime_name2_options
    )
)


# 日期范围 / Date range
min_date = (
    df["Date"]
    .min()
    .date()
)

max_date = (
    df["Date"]
    .max()
    .date()
)


selected_date_range = (
    st.sidebar.date_input(
        "Date Range",
        value=(
            min_date,
            max_date
        ),
        min_value=min_date,
        max_value=max_date
    )
)


# 小时范围 / Hour range
selected_hour_range = (
    st.sidebar.slider(
        "Hour of Day",
        min_value=0,
        max_value=23,
        value=(
            0,
            23
        ),
        step=1
    )
)


# 建立筛选数据 / Build filtered dataset
filtered_df = df


# 应用 Crime Name1 / Apply Crime Name1
if selected_crime_name1 != "All":

    filtered_df = filtered_df[
        filtered_df["Crime Name1"]
        .astype(str)
        == selected_crime_name1
    ]


# 应用 Crime Name2 / Apply Crime Name2
if selected_crime_name2 != "All":

    filtered_df = filtered_df[
        filtered_df["Crime Name2"]
        .astype(str)
        == selected_crime_name2
    ]


# 应用日期范围 / Apply date range
if len(selected_date_range) == 2:

    start_date = (
        selected_date_range[0]
    )

    end_date = (
        selected_date_range[1]
    )

    filtered_df = filtered_df[
        (
            filtered_df["Date"] >= pd.Timestamp(start_date)
        )
        &
        (
            filtered_df["Date"] <= pd.Timestamp(end_date)
        )
    ]


else:
    st.info("Select both the start and end dates.")
    st.stop()

# 应用小时范围 / Apply hour range
start_hour = (
    selected_hour_range[0]
)

end_hour = (
    selected_hour_range[1]
)


filtered_df = filtered_df[
    filtered_df["Hour"].between(
        start_hour,
        end_hour
    )
]


st.caption(f"Selected hours: {start_hour:02d}:00–{end_hour:02d}:59 (inclusive).")

# 统计指标 / Summary metrics
distinct_incidents = (
    filtered_df[
        "Incident ID"
    ]
    .nunique()
)


mappable_incidents = (
    filtered_df.loc[
        filtered_df[
            "Valid_Coordinates"
        ],
        "Incident ID"
    ]
    .nunique()
)


if distinct_incidents > 0:

    map_coverage = (
        mappable_incidents
        / distinct_incidents
        * 100
    )

else:

    map_coverage = 0


col1, col2, col3 = (
    st.columns(3)
)


with col1:

    st.metric(
        "Distinct Incidents",
        f"{distinct_incidents:,}"
    )


with col2:

    st.metric(
        "Mappable Incidents",
        f"{mappable_incidents:,}"
    )


with col3:

    st.metric(
        "Map Coverage",
        f"{map_coverage:.1f}%"
    )


st.divider()


# 保留有效地图坐标 / Keep valid map coordinates
mappable_df = filtered_df.loc[
    filtered_df["Valid_Coordinates"].fillna(False),
    ["Incident ID", "Latitude", "Longitude"],
].copy()

# 确保经纬度为数值 / Ensure numeric coordinates
for column in ["Latitude", "Longitude"]:
    mappable_df[column] = pd.to_numeric(
        mappable_df[column],
        errors="coerce",
    )

mappable_df = mappable_df.dropna(
    subset=["Incident ID", "Latitude", "Longitude"]
)

# 避免同一案件在同一坐标重复计数
map_df = mappable_df.drop_duplicates(
    subset=["Incident ID", "Latitude", "Longitude"]
)

if map_df.empty:
    st.warning("No mappable incidents match the selected filters.")
    st.stop()

# 按精确经纬度汇总不同案件数，不对坐标四舍五入
point_df = (
    map_df.groupby(
        ["Latitude", "Longitude"],
        as_index=False,
        observed=True,
    )["Incident ID"]
    .nunique()
    .rename(columns={"Incident ID": "Incident_Count"})
)

# 百分位：案件数 <= 当前点案件数的坐标点占比
# method="max" 使案件数相同的点获得相同的累计百分位
point_df["Count_Percentile"] = (
    point_df["Incident_Count"]
    .rank(method="max", pct=True)
    .mul(100)
)

# 提前格式化悬停文本
point_df["Count_Label"] = point_df["Incident_Count"].map(
    lambda value: f"{int(value):,}"
)
point_df["Latitude_Label"] = point_df["Latitude"].map(
    lambda value: f"{value:.6f}"
)
point_df["Longitude_Label"] = point_df["Longitude"].map(
    lambda value: f"{value:.6f}"
)
point_df["Percentile_Label"] = point_df["Count_Percentile"].map(
    lambda value: f"{value:.1f}%"
)

# 小案件数先画，大案件数后画，方便选择重叠区域中的高计数点
point_df = point_df.sort_values(
    ["Incident_Count", "Latitude", "Longitude"]
).reset_index(drop=True)

show_hover_points = st.checkbox(
    "Show hover points",
    value=True,
    help="Hover over a point to inspect its incident count and percentile.",
)

# 地图视角 / Map view
view_state = pdk.ViewState(
    latitude=39.13,
    longitude=-77.20,
    zoom=9.4,
    pitch=0,
)

# 热力图：按每个坐标的案件数加权
heatmap_layer = pdk.Layer(
    "HeatmapLayer",
    id="crime-heatmap",
    data=point_df[
        ["Latitude", "Longitude", "Incident_Count"]
    ],
    get_position=["Longitude", "Latitude"],
    get_weight="Incident_Count",
    aggregation="SUM",
    radius_pixels=35,
    intensity=1,
    threshold=0.03,
    pickable=False,
    color_range=[
        [255, 255, 178, 255],
        [254, 217, 118, 255],
        [254, 178, 76, 255],
        [253, 141, 60, 255],
        [240, 59, 32, 255],
        [189, 0, 38, 255],
    ],
)

layers = [heatmap_layer]

if show_hover_points:
    # 可悬停小圆点 / Pickable point overlay
    point_layer = pdk.Layer(
        "ScatterplotLayer",
        id="crime-hover-points",
        data=point_df,
        get_position=["Longitude", "Latitude"],
        radius_units="pixels",
        get_radius=4,
        filled=True,
        stroked=True,
        get_fill_color=[120, 30, 30, 65],
        get_line_color=[100, 30, 30, 130],
        line_width_units="pixels",
        get_line_width=0.5,
        pickable=True,
        auto_highlight=True,
        highlight_color=[255, 255, 255, 220],
    )
    layers.append(point_layer)

# 悬停信息 / Tooltip
tooltip = {
    "html": (
        "<b>Recorded location</b><br/>"
        "<b>Distinct incidents:</b> {Count_Label}<br/>"
        "<b>Latitude:</b> {Latitude_Label}<br/>"
        "<b>Longitude:</b> {Longitude_Label}<br/>"
        "<b>Incident-count percentile:</b> {Percentile_Label}"
    ),
    "style": {
        "backgroundColor": "#202938",
        "color": "#ffffff",
        "fontSize": "14px",
        "padding": "12px",
        "borderRadius": "8px",
    },
}

deck = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    map_style="light",
    tooltip=tooltip,
)

st.pydeck_chart(
    deck,
    use_container_width=True,
    height=700,
)

# 热力图图例 / Heatmap legend
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

st.caption(
    "Hover over a point to view distinct incidents at that exact "
    "recorded coordinate. Zoom in to separate nearby points. "
    "Counts and percentiles update with the selected filters."
)

st.caption(
    "The incident-count percentile is the percentage of mapped "
    "locations with an incident count less than or equal to this "
    "location's count. Tied counts receive the same percentile. "
    "Only locations with matching incidents are included; "
    "this is not a measure of personal victimization risk."
)

st.caption(
    "Heatmap colors show smoothed relative density across nearby "
    "locations, while tooltips describe individual recorded coordinates. "
    "Multiple offense rows from the same incident at the same location "
    "are counted once. An incident recorded at multiple locations can "
    "appear at each location, so point counts may sum to more than "
    "the countywide distinct incident count."
)
