from datetime import timedelta

import plotly.express as px
import streamlit as st

from data_service import CRIME_TYPES, CrimeDataError, county_today
from forecast_service import get_forecast_bundle
from model import DISTRICT, predict_hourly_window
from ui import setup_page

setup_page("Crime Risk Forecast", "🔮")
st.write("Estimate recorded incidents by district for a selected date and time window.")
today = county_today()
st.sidebar.header("Forecast settings")
crime = st.sidebar.selectbox("Crime Type", CRIME_TYPES, index=2)
forecast_date = st.sidebar.date_input("Forecast Date", value=today, min_value=today, max_value=today + timedelta(days=6))
hours = st.sidebar.slider("Hour Range", 0, 23, (18, 22), step=1)
st.sidebar.caption(f"{hours[0]:02d}:00–{hours[1]:02d}:59 inclusive, Eastern Time.")
key = (crime, today.isoformat())
if st.sidebar.button("Generate forecast", type="primary"):
    st.session_state["forecast_key"] = key
if st.session_state.get("forecast_key") != key:
    st.info("Select a crime type and click Generate forecast. The first run compares four models and can take several minutes. Afterward, dates and hour windows update from the same seven-day results.")
    st.page_link("pages/5_Forecast_Methodology.py", label="How the forecast is built", icon="📘")
    st.stop()
try:
    with st.spinner("Requesting online history, validating four models and preparing seven days of forecasts…"):
        bundle = get_forecast_bundle(*key)
    result = predict_hourly_window(bundle, forecast_date, *hours)
except (CrimeDataError, ValueError) as exc:
    st.error(str(exc))
    st.info("Check the online connection or refresh the data, then generate the forecast again.")
    st.stop()

# 仅在会话内保存方法摘要 / Keep the method summary only in session memory
st.session_state["forecast_summary"] = {name: bundle[name] for name in ["crime_name1", "today", "history_end", "best_model", "model_results", "training_start", "effective_training_start", "training_end", "validation_start", "validation_end", "training_rows", "validation_rows", "resolved_incident_conflicts", "loaded_at"]}
forecast = result["district_forecast"]
st.subheader(crime)
st.caption(f"{forecast_date:%B %d, %Y} · {hours[0]:02d}:00–{hours[1]:02d}:59 ET · History through {bundle['history_end']:%Y-%m-%d} · Selected model: {bundle['best_model']}")
gap = (bundle["today"] - bundle["history_end"]).days - 1
if gap > 0:
    st.warning(f"The latest recorded occurrence date is {gap} day(s) earlier than yesterday. Unobserved trailing days are not filled as zero; recent averages end on the displayed history date.")
st.caption("Today's records are excluded from training. Recent records can still be incomplete because reporting and source updates take time.")
cols = st.columns(4)
highest = forecast.loc[forecast["Incident_Probability"].idxmax()]
cols[0].metric("Expected incidents", f"{forecast['Expected_Incidents'].sum():.2f}")
cols[1].metric("Highest probability district", str(highest[DISTRICT]).title())
cols[2].metric("Highest estimated probability", f"{highest['Incident_Probability']:.1%}")
cols[3].metric("Above-normal districts", int(forecast["Risk_Level"].isin(["High", "Elevated"]).sum()))

st.subheader("District forecast")
colors = {"Normal": "#4C78A8", "Elevated": "#E7A54B", "High": "#CC5A52"}
fig = px.bar(forecast.sort_values("Expected_Incidents"), x="Expected_Incidents", y=DISTRICT, orientation="h", color="Risk_Level", color_discrete_map=colors, text_auto=".2f", labels={"Expected_Incidents": "Expected incidents", "Risk_Level": "Relative risk"})
fig.update_layout(height=430)
st.plotly_chart(fig, use_container_width=True)
shown = forecast[[DISTRICT, "Expected_Incidents", "Incident_Probability", "Risk_Level", "Recent_7_Window_Avg", "Same_Weekday_Window_Avg"]].copy()
shown["Incident_Probability"] *= 100
shown = shown.rename(columns={"Expected_Incidents": "Expected Incidents", "Incident_Probability": "Probability (%)", "Risk_Level": "Relative Risk", "Recent_7_Window_Avg": "Recent 7-Day Avg", "Same_Weekday_Window_Avg": "Same Weekday Avg"})
st.dataframe(shown, hide_index=True, use_container_width=True, column_config={name: st.column_config.NumberColumn(format="%.2f") for name in ["Expected Incidents", "Probability (%)", "Recent 7-Day Avg", "Same Weekday Avg"]})
st.caption("Probability estimates at least one recorded incident in this district and time window under a Poisson assumption. It is not an individual's risk. Both historical averages use the same selected hours; relative risk compares each district with its own historical distribution.")

st.subheader("Seven-day outlook for the selected hours")
st.plotly_chart(px.line(result["weekly_forecast"], x="Date", y="Expected Incidents", color=DISTRICT, markers=True), use_container_width=True)
with st.expander("Hourly detail and risk thresholds"):
    st.plotly_chart(px.line(result["hourly_forecast"], x="Hour", y="Predicted_Incidents", color=DISTRICT, markers=True, labels={"Predicted_Incidents": "Expected incidents"}), use_container_width=True)
    st.dataframe(forecast[[DISTRICT, "P60", "P85", "Recent_28_Window_Avg"]].round(2), hide_index=True, use_container_width=True)
    st.caption("Thresholds include zero-incident days. With sparse hourly data, P60 and P85 may both equal zero, making relative-risk labels sensitive to small positive expectations.")
st.page_link("pages/5_Forecast_Methodology.py", label="Model comparison, validation and limitations", icon="📘")
