import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import PROFILE_COLORS, PROFILE_ORDER, change_chart, comparison_table, incident_counts, time_heatmap
from data_service import DAY_ORDER, county_today, load_and_clean_data
from ui import load_with_message, setup_page, source_caption

setup_page("Crime Analysis", "📊")
st.write("Explore recorded incidents across area profiles, crime types, time and place.")
df = load_with_message(load_and_clean_data)
source_caption(df)

# 通用筛选 / General filters
st.sidebar.header("Analysis filters")
minimum, maximum = df["Date"].min().date(), df["Date"].max().date()
default_start = max(minimum, pd.Timestamp("2017-01-01").date())
default_end = min(maximum, pd.Timestamp(f"{county_today().year - 1}-12-31").date())
if default_end < default_start:
    default_start, default_end = minimum, maximum
period = st.sidebar.date_input("Date range", value=(default_start, default_end), min_value=minimum, max_value=maximum)
measure = st.sidebar.radio("Measure", ["Distinct Incidents", "Percentage"])
crime_options = ["All"] + sorted(df["Crime Name1"].astype(str).unique().tolist())
crime = st.sidebar.selectbox("Crime type", crime_options)
if len(period) != 2:
    st.info("Select both the start and end dates.")
    st.stop()
start, end = map(pd.Timestamp, period)
filtered = df.loc[df["Date"].between(start, end)]
if crime != "All":
    filtered = filtered.loc[filtered["Crime Name1"].eq(crime)]
if filtered.empty:
    st.info("No incidents match the selected filters.")
    st.stop()
known = filtered.loc[filtered["Area_Profile"].isin(PROFILE_ORDER)]
unknown = filtered.loc[filtered["Area_Profile"].eq("Unknown"), "Incident ID"].nunique()
cols = st.columns(3)
cols[0].metric("Distinct incidents", f"{filtered['Incident ID'].nunique():,}")
cols[1].metric("Selected period", f"{start.year}–{end.year}")
cols[2].metric("Incidents with unknown area profile", f"{unknown:,}")
st.caption("High, Mix and Low/Mid are ZIP-level area proxies, not individual income. Raw counts do not adjust for population or exposure. Unknown profiles remain in county, district, ZIP and time-heatmap analyses.")
profile_totals = known.groupby("Area_Profile", observed=True)["Incident ID"].nunique()


def plot_profile(data, x, title, kind="bar", order=None, annual=False):
    data = data.copy()
    y = "Incidents"
    if measure == "Percentage":
        if annual:
            denominators = known.groupby("Year", observed=True)["Incident ID"].nunique()
            data["Percentage"] = 100 * data["Incidents"] / data["Year"].map(denominators).astype(float)
        else:
            data["Percentage"] = 100 * data["Incidents"] / data["Area_Profile"].map(profile_totals).astype(float)
        y = "Percentage"
    kwargs = dict(data_frame=data, x=x, y=y, color="Area_Profile", color_discrete_map=PROFILE_COLORS, category_orders={"Area_Profile": PROFILE_ORDER, **({x: order} if order else {})}, labels={"Area_Profile": "Area profile"}, title=title)
    fig = px.line(**kwargs, markers=True) if kind == "line" else px.bar(**kwargs, barmode="group")
    fig.update_layout(height=370, legend_title_text="Area profile")
    if x == "Year":
        fig.update_xaxes(dtick=1)
    if measure == "Percentage":
        fig.update_yaxes(ticksuffix="%")
    st.plotly_chart(fig, use_container_width=True)


if known.empty:
    st.info("The selected records have no mapped High, Mix or Low/Mid profiles. Geographic and time comparisons remain below.")
else:
    st.subheader("1 · Annual Crime Trend by Area Profile")
    plot_profile(incident_counts(known, ["Year", "Area_Profile"]), "Year", "Annual recorded incidents", "line", annual=True)
    if start != pd.Timestamp(start.year, 1, 1) or end != pd.Timestamp(end.year, 12, 31):
        st.caption("The first or last year is a partial period; do not compare it as a complete year.")
    st.caption("In percentage mode, each profile is divided by all distinct incidents with a known profile in that year.")

    st.subheader("2 · Crime Type Composition")
    plot_profile(incident_counts(known, ["Crime Name1", "Area_Profile"]), "Crime Name1", "Crime types within each area profile")
    st.caption("Percentage uses distinct incidents within each profile as the denominator. An incident can contain multiple crime categories, so category percentages may sum above 100%.")

    st.subheader("3 · Crime by Hour of Day")
    plot_profile(incident_counts(known, ["Hour", "Area_Profile"]), "Hour", "Occurrence / start hour", "line")
    st.subheader("4 · Crime by Day of Week")
    plot_profile(incident_counts(known, ["Day_of_Week", "Area_Profile"]), "Day_of_Week", "Occurrence / start weekday", order=DAY_ORDER)
    st.caption("Hourly and weekday percentages use all distinct incidents within each profile, under the selected filters.")

    st.subheader("5 · Top Place Types by Area Profile")
    top_places = known.groupby("Place", observed=True)["Incident ID"].nunique().nlargest(10).index.tolist()
    places = incident_counts(known.loc[known["Place"].isin(top_places)], ["Place", "Area_Profile"])
    plot_profile(places, "Place", "Ten leading place types across known profiles", order=top_places)
    st.caption("Place percentages use all incidents in the profile, including places outside the displayed top ten.")

# 完整年份比较 / Compare complete years
st.subheader("6 · Police District Year-to-Year Change")
years = [int(y) for y in sorted(filtered["Year"].unique()) if y < county_today().year and start <= pd.Timestamp(int(y), 1, 1) and end >= pd.Timestamp(int(y), 12, 31)]
if len(years) >= 2:
    left, right = st.columns(2)
    comparison = left.selectbox("Comparison year", years[1:], index=len(years) - 2)
    baselines = [y for y in years if y < comparison]
    baseline = right.selectbox("Baseline year", baselines, index=len(baselines) - 1)
    district_table = comparison_table(filtered, "Police District Name", baseline, comparison)
    st.plotly_chart(change_chart(district_table, "Police District Name", f"District change · {baseline} → {comparison}"), use_container_width=True)
    with st.expander("District counts and percentage changes"):
        st.dataframe(district_table, hide_index=True, use_container_width=True)
    st.subheader("7 · ZIP Code Year-to-Year Change")
    zip_table = comparison_table(filtered, "Zip Code", baseline, comparison)
    st.plotly_chart(change_chart(zip_table.loc[zip_table["Zip Code"].ne("Unknown")], "Zip Code", f"Largest ZIP increases and decreases · {baseline} → {comparison}", limit=16), use_container_width=True)
    with st.expander("All ZIP counts, including unknown ZIP"):
        st.dataframe(zip_table, hide_index=True, use_container_width=True)
    st.caption("Change charts always show count differences; tables include percentage changes. A zero baseline has an undefined percentage change. All area profiles are included, with the current crime-type filter.")
else:
    st.info("Sections 6 and 7 require a date range containing at least two complete calendar years.")

st.subheader("8 · Day × Hour Heatmap")
st.plotly_chart(time_heatmap(filtered), use_container_width=True)
st.caption("Distinct incident counts by recorded Start_Date_Time. This heatmap includes unknown area profiles and always shows counts, regardless of the measure toggle. It does not use dispatch time.")
