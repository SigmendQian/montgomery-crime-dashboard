import pandas as pd
import streamlit as st

from data_service import DATASET_URL
from ui import setup_page

setup_page("Forecast Methodology", "📘")
st.write("How online records become a seven-day district forecast, and what the results mean.")
st.caption("Historical records → Cleaning → Hourly counts → Historical features → Time-based validation → Model selection → Refit → Seven-day forecast")

st.subheader("1 · Objective and prediction unit")
st.write("Predict the number of distinct recorded incidents for each date × police district × hour, for the selected crime type. Add the hourly expectations to cover the user's inclusive hour window. Forecasts span today through today + 6 days, using America/New_York dates.")
st.write("The shared source retains all offense rows. Within the selected forecasting subset only, an incident is assigned to its earliest valid occurrence/start timestamp; if that timestamp ties across districts, alphabetical district order breaks the tie. This prevents an event from being counted again when hours are added. All is aggregated directly from incident IDs across included crime types, never by adding category forecasts. Unknown and OTHER districts are excluded.")

st.subheader("2 · Data cutoff and zero-count hours")
st.write("Only records dated strictly before today are eligible. The history ends at the earlier of yesterday and the latest eligible occurrence date available from the county source. The hourly grid includes zero-count hours and days within that observed history. Days beyond the available history are not invented as zero observations.")
st.caption("The latest occurrence date is not a guarantee that all incidents through that date have been reported. Recent counts may be revised.")

st.subheader("3 · Feature engineering")
st.dataframe(pd.DataFrame([
    ("Police District", "District identity, encoded categorically."),
    ("Hour, weekday, month, weekend", "Known calendar properties of the target date and hour."),
    ("Recent_7_Daily_Avg", "Mean daily distinct incidents in the seven days before the forecast origin."),
    ("Recent_28_Daily_Avg", "Mean daily distinct incidents in the 28 days before the origin."),
    ("Same_Hour_Avg", "Historical mean for this district and hour before the origin, including zero hours."),
    ("Recent_Same_Hour_Avg", "Mean for this district and hour over the 28 days before the origin."),
    ("Same_Weekday_Hour_Avg", "Historical mean for this district, target weekday and hour before the origin."),
], columns=["Feature", "Meaning"]), hide_index=True, use_container_width=True)
st.write("Eight weeks are reserved for initial history. Each seven-day forecast freezes the historical features at its origin; days 2–7 use their own known calendar values without feeding earlier predictions or future actual counts back into the model.")

st.subheader("4 · Training and validation")
st.write("The training period is 2017-01-01 through 2025-12-31, with the first eight weeks used for feature warm-up. Validation runs from 2026-01-01 through the available complete date before today. There is no separate test set.")
st.write("Validation is issued in consecutive seven-day blocks beginning January 1, 2026. All features for a block use records strictly before its first day; the final block may contain fewer than seven observed days. As time advances, earlier validation outcomes may enter the history of later blocks. Candidate models themselves remain fitted only on the 2017–2025 training targets during comparison. Training examples use the same seven-day feature-freezing design.")
st.caption("This evaluates a seven-day forecasting procedure using the currently available version of historical records. It cannot reconstruct when every record was originally published or later corrected.")

st.subheader("5 · Candidate models and selection")
st.dataframe(pd.DataFrame([
    ("Historical Hourly Average", "Uses the historical mean for the same district, weekday and hour."),
    ("Poisson Regression", "A regularized count model using district and time/history features."),
    ("Random Forest", "Captures nonlinear interactions; 150 trees, depth 12, leaf size 5, 35% bootstrap samples, two workers."),
    ("HistGradientBoosting", "Boosted trees with Poisson loss; 200 iterations and controlled tree size."),
], columns=["Candidate", "Role"]), hide_index=True, use_container_width=True)
st.write("Select the eligible model with the lowest validation MAE. MAE is the average absolute count error per district-hour. RMSE is also reported and emphasizes larger errors, but does not override the MAE selection. Then refit the selected model on all eligible feature rows before today and generate seven days of predictions. Models are not written to disk.")
summary = st.session_state.get("forecast_summary")
if summary:
    with st.container(border=True):
        st.markdown(f"**Latest forecast in this session: {summary['crime_name1']}**")
        st.caption(f"Issued {summary['today']:%Y-%m-%d} · History through {summary['history_end']:%Y-%m-%d} · Source retrieved {summary['loaded_at'][:19]}")
        st.write(f"Selected model: **{summary['best_model']}**. Training rows: {summary['training_rows']:,}; validation rows: {summary['validation_rows']:,}.")
        st.dataframe(summary["model_results"].round(4), hide_index=True, use_container_width=True)
        st.caption(f"Model-specific event assignment resolved {summary['resolved_incident_conflicts']:,} incidents with multiple start times or districts. Effective training targets begin {summary['effective_training_start']:%Y-%m-%d}.")
else:
    st.info("Generate a forecast on Page 4 to see the actual model comparison here. No example accuracy numbers are substituted.")

st.subheader("6 · Expected counts and estimated probability")
st.latex(r"\lambda_{\mathrm{window}}=\sum_{h=h_{\mathrm{start}}}^{h_{\mathrm{end}}}\widehat{\lambda}_h")
st.latex(r"P(X\geq1)=1-e^{-\lambda_{\mathrm{window}}}")
st.write("λ is the expected count in the selected district and time window. X is the number of recorded incidents. The conversion assumes a Poisson count distribution for the window; model counts alone do not guarantee calibrated probabilities. Hourly dependence and overdispersion can weaken this approximation. Decimal expected counts are normal.")

st.subheader("7 · Relative risk and historical comparisons")
st.dataframe(pd.DataFrame([
    ("Normal", "Expected window count ≤ the district's historical P60."),
    ("Elevated", "Above P60 and at or below P85."),
    ("High", "Above P85."),
], columns=["Relative risk", "Rule"]), hide_index=True, use_container_width=True)
st.write("P60 and P85 are the 60th and 85th percentiles of historical daily counts in the same hour window, calculated separately for each district using the modeled history, including zero days. They are not probability thresholds. The Recent 7-Day Avg uses the last seven observed calendar days; the Same Weekday Avg uses all historical days matching the selected weekday. Both use the same selected hours.")

st.subheader("8 · Limitations")
st.markdown("""
- Recorded crime is affected by reporting, dispatch and data revisions; it is not a measure of all crimes that occurred.
- Raw incident counts do not adjust for population, traffic, visitors or other exposure.
- Occurrence/start times can be approximate, especially when an event was discovered later.
- Unreported observations within the historical range can be mistaken for zero recorded activity.
- A model selected on this validation period has no independent test-set performance estimate.
- Sparse hours can produce zero percentile thresholds and unstable relative-risk labels.
- The forecast does not explain causes or identify offenders, victims or an individual's risk.
""")
st.markdown(f"[County dataset and field definitions]({DATASET_URL}) · [Poisson regression documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.PoissonRegressor.html)")
st.page_link("pages/4_Crime_Risk_Forecast.py", label="Return to forecast", icon="🔮")
