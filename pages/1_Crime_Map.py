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
mappable_df = (
    filtered_df[
        filtered_df[
            "Valid_Coordinates"
        ]
    ]
    .copy()
)


# 避免同一案件重复绘制 / Avoid duplicate incident points
map_df = (
    mappable_df[
        [
            "Incident ID",
            "Latitude",
            "Longitude",
        ]
    ]
    .drop_duplicates(
        subset=[
            "Incident ID",
            "Latitude",
            "Longitude",
        ]
    )
)


# 地图视角 / Map view
view_state = pdk.ViewState(
    latitude=39.13,
    longitude=-77.20,
    zoom=9.4,
    pitch=0
)


# 犯罪密度热力图 / Crime density heatmap
heatmap_layer = pdk.Layer(
    "HeatmapLayer",

    data=map_df,

    get_position=[
        "Longitude",
        "Latitude"
    ],

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
    ]
)


# 创建地图 / Build map
deck = pdk.Deck(
    layers=[
        heatmap_layer
    ],
    initial_view_state=view_state,
    map_style="light"
)


# 显示地图 / Display map
if map_df.empty:

    st.warning(
        "No mappable incidents match the selected filters."
    )

else:

    st.pydeck_chart(
        deck,
        use_container_width=True,
        height=700
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
    '<span style="font-size:14px;">'
    'High'
    '</span>'
    '</div>',
    unsafe_allow_html=True
)


# 地图说明 / Map note
st.caption(
    "The heatmap displays distinct incidents with valid coordinates. "
    "Multiple offense rows belonging to the same incident at the same "
    "location are not plotted repeatedly."
)