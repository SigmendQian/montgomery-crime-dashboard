import pandas as pd
import plotly.express as px
import streamlit as st

from data_service import load_and_clean_data
from ui import setup_page, load_with_message, source_caption


# 页面与在线数据 / Page and online data
setup_page("Crime Map", "🗺️")

st.write(
    "Explore the spatial distribution of crime incidents "
    "across Montgomery County."
)

df = load_with_message(load_and_clean_data)
source_caption(df)

if df.empty:
    st.warning("No crime records are available.")
    st.stop()


# 侧边栏筛选 / Sidebar filters
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

# Crime Name2 联动筛选
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

# 日期范围
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

# 小时范围，包含结束小时
selected_hour_range = st.sidebar.slider(
    "Hour of Day",
    min_value=0,
    max_value=23,
    value=(0, 23),
    step=1,
)


# 应用筛选 / Apply filters
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

# 使用结束日期的次日作为右侧边界，涵盖结束日全天
start_timestamp = pd.Timestamp(start_date)
end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1)

filtered_df = filtered_df.loc[
    filtered_df["Date"].ge(start_timestamp)
    & filtered_df["Date"].lt(end_timestamp)
]

start_hour, end_hour = selected_hour_range

filtered_df = filtered_df.loc[
    filtered_df["Hour"].between(start_hour, end_hour)
]

st.caption(
    f"Selected hours: "
    f"{start_hour:02d}:00–{end_hour:02d}:59 (inclusive)."
)


# 准备地图数据 / Prepare map data
# 只在内存中处理远程数据，不读取或写入本地犯罪数据
mappable_df = filtered_df.loc[
    filtered_df["Valid_Coordinates"].fillna(False),
    ["Incident ID", "Latitude", "Longitude"],
].copy()

for column in ["Latitude", "Longitude"]:
    mappable_df[column] = pd.to_numeric(
        mappable_df[column],
        errors="coerce",
    )

mappable_df = mappable_df.dropna(
    subset=["Incident ID", "Latitude", "Longitude"]
)

mappable_df = mappable_df.loc[
    mappable_df["Latitude"].between(-90, 90)
    & mappable_df["Longitude"].between(-180, 180)
]

# 同一案件在同一坐标只保留一次
map_df = mappable_df.drop_duplicates(
    subset=["Incident ID", "Latitude", "Longitude"]
)


# 统计指标 / Summary metrics
distinct_incidents = filtered_df["Incident ID"].nunique()
mappable_incidents = map_df["Incident ID"].nunique()

map_coverage = (
    mappable_incidents / distinct_incidents * 100
    if distinct_incidents > 0
    else 0
)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Distinct Incidents",
        f"{distinct_incidents:,}",
    )

with col2:
    st.metric(
        "Mappable Incidents",
        f"{mappable_incidents:,}",
    )

with col3:
    st.metric(
        "Map Coverage",
        f"{map_coverage:.1f}%",
    )

st.divider()

if map_df.empty:
    st.warning(
        "No mappable incidents match the selected filters."
    )
    st.stop()


# 按精确坐标汇总案件数量 / Count incidents per coordinate
# 不对经纬度四舍五入，不合并附近的不同位置
location_counts = (
    map_df.groupby(
        ["Latitude", "Longitude"],
        as_index=False,
        observed=True,
    )["Incident ID"]
    .nunique()
    .rename(columns={"Incident ID": "Incident_Count"})
)

location_counts["Incident_Count"] = (
    location_counts["Incident_Count"].astype(int)
)


# 热力图设置 / Heatmap settings
heatmap_colors = [
    "rgb(255,255,178)",
    "rgb(254,217,118)",
    "rgb(254,178,76)",
    "rgb(253,141,60)",
    "rgb(240,59,32)",
    "rgb(189,0,38)",
]

map_center = {
    "lat": 39.13,
    "lon": -77.20,
}

chart_options = {
    "data_frame": location_counts,
    "lat": "Latitude",
    "lon": "Longitude",

    # 每个位置按不同案件数量加权
    "z": "Incident_Count",

    # 将案件数量传给原生悬停提示
    "custom_data": ["Incident_Count"],

    "radius": 25,
    "center": map_center,
    "zoom": 9.4,
    "height": 700,
    "opacity": 0.85,
    "color_continuous_scale": heatmap_colors,
}

# 与参考项目一致：优先使用 density_map
# 同时兼容只有 density_mapbox 的旧版 Plotly
if hasattr(px, "density_map"):
    fig = px.density_map(
        **chart_options,
        map_style="carto-positron",
    )
else:
    fig = px.density_mapbox(
        **chart_options,
        mapbox_style="carto-positron",
    )

# 仅使用热力图本身的悬停，无额外散点图层
fig.update_traces(
    hovertemplate=(
        "<b>Recorded location</b><br>"
        "Latitude: %{lat:.6f}<br>"
        "Longitude: %{lon:.6f}<br>"
        "<b>Distinct incidents: %{customdata[0]:,.0f}</b>"
        "<extra></extra>"
    )
)

fig.update_layout(
    margin=dict(l=0, r=0, t=0, b=0),
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(
        family="Arial, sans-serif",
        size=13,
    ),
    hoverlabel=dict(
        bgcolor="#202938",
        bordercolor="#202938",
        font=dict(
            color="white",
            size=14,
        ),
    ),

    # 使用下方相对密度图例，避免把颜色误读为精确案件数
    coloraxis_showscale=False,
)

st.plotly_chart(
    fig,
    use_container_width=True,
    key="crime_density_map_native_hover",
    config={
        "scrollZoom": True,
        "displaylogo": False,
    },
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


# 地图说明 / Map notes
st.caption(
    "Hover near a recorded location on the heatmap to view its "
    "latitude, longitude, and distinct incident count. "
    "Zoom in to distinguish nearby locations."
)

st.caption(
    "Tooltip counts refer to the exact recorded coordinate under "
    "the selected filters, not the entire surrounding heatmap area. "
    "Multiple offense rows for the same incident at the same "
    "location are counted once."
)

st.caption(
    "Heatmap colors show smoothed relative incident density, "
    "not personal victimization probability. An incident recorded "
    "at multiple locations can contribute to each location."
)
