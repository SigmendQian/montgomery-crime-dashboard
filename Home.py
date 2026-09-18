import streamlit as st

from data_service import CrimeDataError, get_remote_status
from ui import setup_page

setup_page("Montgomery County Crime Dashboard", "📊")
st.write("Explore recorded crime, investigate local patterns, and estimate activity over the next seven days.")
st.caption("Explore → Describe → Investigate → Predict → Explain")

# 导航先展示 / Render navigation before loading
pages = [
    ("1 · Crime Map", "Where are incidents concentrated? Filter recorded incidents by crime type, date and hour.", "pages/1_Crime_Map.py", "🗺️"),
    ("2 · Crime Analysis", "Compare area profiles, crime composition, timing, places and year-to-year geographic change.", "pages/2_Crime_Analysis.py", "📊"),
    ("3 · Targeted Analysis Results", "Follow a vehicle-break-in case study from the county trend to districts, ZIP codes and reporting patterns.", "pages/3_Targeted_Analysis_Results.py", "🔎"),
    ("4 · Crime Risk Forecast", "Choose a date and hour window to estimate district incident counts, probabilities and relative risk.", "pages/4_Crime_Risk_Forecast.py", "🔮"),
    ("5 · Forecast Methodology", "Understand the data cutoff, features, validation, model selection and interpretation limits.", "pages/5_Forecast_Methodology.py", "📘"),
]
for first in (0, 3):
    cols = st.columns(3 if first == 0 else 2)
    for col, (name, description, path, icon) in zip(cols, pages[first:first + len(cols)]):
        with col, st.container(border=True):
            st.subheader(name)
            st.write(description)
            st.page_link(path, label="Open page", icon=icon)
st.divider()
st.subheader("Online data overview")
try:
    with st.spinner("Checking the online data summary…"):
        status = get_remote_status()
    cols = st.columns(3)
    cols[0].metric("Distinct incidents", f"{int(status.get('incidents', 0)):,}")
    cols[1].metric("Latest occurrence date", str(status.get("latest", "Unavailable"))[:10])
    cols[2].metric("Source", "County Open Data")
except CrimeDataError as exc:
    st.warning(str(exc))
st.caption("Totals exclude non-crime records and future occurrence dates. Reported records are not a per-capita crime rate or an individual's risk. Occurrence dates do not establish reporting completeness.")
