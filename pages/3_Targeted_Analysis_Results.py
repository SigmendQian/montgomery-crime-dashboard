import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import case_takeaway, change_chart, comparison_table, incident_counts, time_heatmap
from data_service import OFFENSE_NAME, county_today, load_targeted_vehicle_theft_data
from ui import load_with_message, setup_page, source_caption

setup_page("Targeted Analysis Results", "🔎")
st.subheader("Theft From Motor Vehicle")
st.write("Did a change in countywide vehicle break-ins conceal increases in particular districts and ZIP codes?")
st.sidebar.header("Case-study years")
years = list(range(2017, county_today().year))
comparison = st.sidebar.selectbox("Comparison year", years[1:], index=years[1:].index(2025) if 2025 in years[1:] else len(years) - 2)
baselines = [y for y in years if y < comparison]
baseline = st.sidebar.selectbox("Baseline year", baselines, index=baselines.index(2024) if 2024 in baselines else len(baselines) - 1)
df = load_with_message(load_targeted_vehicle_theft_data, baseline, comparison)
source_caption(df)
st.caption(f"Scope: Crime Name2 = {OFFENSE_NAME}. Years are based on occurrence / start time. Every headline below is recalculated from the online records.")
base_n = int(df.loc[df["Year"].eq(baseline), "Incident ID"].nunique())
comp_n = int(df.loc[df["Year"].eq(comparison), "Incident ID"].nunique())
change = comp_n - base_n
pct_text = f"{change / base_n:+.1%}" if base_n else "Undefined: zero baseline"

st.subheader("1 · County trend")
cols = st.columns(3)
cols[0].metric(f"{baseline} incidents", f"{base_n:,}")
cols[1].metric(f"{comparison} incidents", f"{comp_n:,}")
cols[2].metric("Change", f"{change:+,}", pct_text, delta_color="inverse")
trend = incident_counts(df, ["Year"])
trend["Year"] = trend["Year"].astype(str)
st.plotly_chart(px.bar(trend, x="Year", y="Incidents", text="Incidents", title="Countywide distinct incidents", color_discrete_sequence=["#4C78A8"]), use_container_width=True)

st.subheader("2 · District redistribution")
districts = comparison_table(df, "Police District Name", baseline, comparison)
st.plotly_chart(change_chart(districts, "Police District Name", f"Changes by police district · {baseline} → {comparison}"), use_container_width=True)
st.dataframe(districts, hide_index=True, use_container_width=True)
known_districts = districts.loc[~districts["Police District Name"].astype(str).str.upper().isin(["UNKNOWN", "OTHER"])]
if not known_districts.empty:
    up = known_districts.loc[known_districts["Change"].gt(0)]
    down = known_districts.loc[known_districts["Change"].lt(0)]
    st.write(f"{len(up)} districts increased and {len(down)} decreased. These opposing changes must be read alongside the county total.")

st.subheader("3 · ZIP redistribution")
zips = comparison_table(df, "Zip Code", baseline, comparison)
st.plotly_chart(change_chart(zips.loc[zips["Zip Code"].ne("Unknown")], "Zip Code", "Strongest ZIP-level increases and decreases", limit=16), use_container_width=True)
with st.expander("Full ZIP comparison"):
    st.dataframe(zips, hide_index=True, use_container_width=True)
st.caption("Count changes and percentage changes answer different questions. A small baseline can produce a large percentage increase. Unknown locations remain in totals; group totals may overlap when one incident has multiple recorded locations.")

st.subheader("4 · Place environment")
current = df.loc[df["Year"].eq(comparison)]
places = incident_counts(current, ["Place"]).nlargest(10, "Incidents").sort_values("Incidents")
st.plotly_chart(px.bar(places, x="Incidents", y="Place", orientation="h", text="Incidents", title=f"Leading recorded place types · {comparison}", color_discrete_sequence=["#4C78A8"]), use_container_width=True)
if not places.empty:
    leaders = places.nlargest(3, "Incidents")["Place"].astype(str).tolist()
    st.write("The three leading recorded environments are " + ", ".join(leaders) + ".")
residential_places = ["Street - Residential", "Parking Lot - Residential", "Residence - Driveway", "Parking Garage - Residential"]
residential = int(current.loc[current["Place"].isin(residential_places), "Incident ID"].nunique())
if comp_n:
    st.write(f"Residential streets, residential parking lots, driveways and residential parking garages together account for {residential:,} distinct incidents ({residential / comp_n:.1%} of the selected year's total). These counts describe recorded settings, not risk per parked vehicle.")

st.subheader("5 · Timing and reporting pattern")
occurrence, dispatch = st.tabs(["Occurrence / start time", "Police dispatch time"])
with occurrence:
    st.plotly_chart(time_heatmap(current), use_container_width=True)
    st.caption("Start_Date_Time records the beginning of the occurrence window. For an unattended vehicle, the exact offense time may be unknown.")
with dispatch:
    timed = current.loc[current["Dispatch Date / Time"].notna()].copy()
    timed_n = timed["Incident ID"].nunique()
    st.caption(f"Dispatch-time coverage: {timed_n:,} of {comp_n:,} distinct incidents. The cohort is selected by occurrence year, even if dispatch took place later.")
    if timed.empty:
        st.info("No usable dispatch timestamps are available for this cohort.")
    else:
        st.plotly_chart(time_heatmap(timed, dispatch=True), use_container_width=True)
        timed["Dispatch period"] = pd.cut(timed["Dispatch Date / Time"].dt.hour, [-1, 5, 11, 17, 23], labels=["Overnight", "Morning", "Afternoon", "Evening"])
        periods = incident_counts(timed, ["Dispatch period"])
        st.plotly_chart(px.bar(periods, x="Dispatch period", y="Incidents", text="Incidents", category_orders={"Dispatch period": ["Overnight", "Morning", "Afternoon", "Evening"]}), use_container_width=True)
        peak = periods.loc[periods["Incidents"].idxmax(), "Dispatch period"]
        st.write(f"The largest dispatch-period total is {peak}. This describes reporting / police demand; it does not establish when the offenses happened.")

st.subheader("6 · Main takeaway")
st.info(case_takeaway(base_n, comp_n, known_districts))
st.write("The district, ZIP and place evidence adds detail that a single county trend cannot show. Geographic differences do not prove movement by the same offenders or explain the causes of change.")
