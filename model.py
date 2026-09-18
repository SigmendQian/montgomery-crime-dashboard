from __future__ import annotations

import gc

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from data_service import county_today

TRAIN_START = pd.Timestamp("2017-01-01")
TRAIN_END = pd.Timestamp("2025-12-31")
VALIDATION_START = pd.Timestamp("2026-01-01")
DISTRICT = "Police District Name"
BASELINE_NAME = "Historical Hourly Average"
NUMERIC_FEATURES = [
    "Hour", "Day_of_Week_Number", "Month", "Is_Weekend", "Recent_7_Daily_Avg",
    "Recent_28_Daily_Avg", "Same_Hour_Avg", "Recent_Same_Hour_Avg", "Same_Weekday_Hour_Avg",
]
FEATURE_COLUMNS = [DISTRICT] + NUMERIC_FEATURES


def get_available_crime_types(df):
    return ["All"] + sorted(set(df["Crime Name1"].dropna().astype(str)) - {"Crime Against Not a Crime"})


# 仅在模型子集中统一事件时点 / Assign one event time only within the model subset
# 主数据的多罪名记录始终保留 / The source offense rows remain intact

def build_hourly_counts(df, crime_name1, history_end):
    end = pd.Timestamp(history_end).normalize()
    valid = ~df[DISTRICT].astype("string").str.upper().isin(["UNKNOWN", "OTHER", ""])
    mask = valid & df[DISTRICT].notna() & df["Date"].between(TRAIN_START, end)
    if crime_name1 != "All":
        mask &= df["Crime Name1"].eq(crime_name1)
    selected = df.loc[mask, ["Incident ID", "Start_Date_Time", DISTRICT]].copy()
    if selected.empty:
        raise ValueError("No valid district incidents are available for this crime type.")
    selected[DISTRICT] = selected[DISTRICT].astype("string")
    selected = selected.sort_values(["Incident ID", "Start_Date_Time", DISTRICT])
    conflicts = int((selected.groupby("Incident ID", observed=True)["Start_Date_Time"].nunique().gt(1) | selected.groupby("Incident ID", observed=True)[DISTRICT].nunique().gt(1)).sum())
    events = selected.drop_duplicates("Incident ID", keep="first").copy()
    events["Date"] = events["Start_Date_Time"].dt.normalize()
    events["Hour"] = events["Start_Date_Time"].dt.hour
    districts = sorted(events[DISTRICT].unique())
    dates = pd.date_range(TRAIN_START, end)
    counts = events.groupby(["Date", DISTRICT, "Hour"], observed=True)["Incident ID"].nunique()
    grid = pd.MultiIndex.from_product([dates, districts, range(24)], names=["Date", DISTRICT, "Hour"])
    result = counts.reindex(grid, fill_value=0).rename("Incident_Count").reset_index()
    result[DISTRICT] = result[DISTRICT].astype("category")
    result["Hour"] = result["Hour"].astype("int8")
    result["Incident_Count"] = result["Incident_Count"].astype("int32")
    result.attrs["resolved_incident_conflicts"] = conflicts
    return result


def _tensor(hourly):
    ordered = hourly.sort_values(["Date", DISTRICT, "Hour"])
    dates = pd.DatetimeIndex(sorted(ordered["Date"].unique()))
    districts = sorted(ordered[DISTRICT].astype(str).unique())
    cube = ordered["Incident_Count"].to_numpy(dtype=np.float32).reshape(len(dates), len(districts), 24)
    return cube, dates, districts


# 每个预测批次冻结历史特征 / Freeze history at each forecast origin

def _feature_frame(cube, history_dates, districts, targets, origins):
    targets = pd.DatetimeIndex(targets)
    origins = np.asarray(origins, dtype=int)
    if np.any(origins < 56) or np.any(origins > len(cube)):
        raise ValueError("At least eight weeks of history are required at every forecast origin.")
    if np.any(targets.to_numpy() < (history_dates[0] + pd.to_timedelta(origins, unit="D")).to_numpy()):
        raise ValueError("Features cannot use the target day or later data.")
    prefix = np.concatenate([np.zeros((1, len(districts), 24)), np.cumsum(cube, axis=0, dtype=np.float64)])
    previous_7 = (prefix[origins] - prefix[origins - 7]).sum(axis=2) / 7
    previous_28 = (prefix[origins] - prefix[origins - 28]).sum(axis=2) / 28
    same_hour = prefix[origins] / origins[:, None, None]
    recent_hour = (prefix[origins] - prefix[origins - 28]) / 28
    same_weekday = np.zeros_like(same_hour)
    weekdays = history_dates.dayofweek.to_numpy()
    for day in range(7):
        positions = np.flatnonzero(weekdays == day)
        target_mask = targets.dayofweek == day
        n_prior = np.searchsorted(positions, origins[target_mask], side="left")
        weekday_prefix = np.concatenate([np.zeros((1, len(districts), 24)), np.cumsum(cube[positions], axis=0, dtype=np.float64)])
        same_weekday[target_mask] = weekday_prefix[n_prior] / n_prior[:, None, None]
    cells = len(districts) * 24
    frame = pd.DataFrame({
        "Date": np.repeat(targets.to_numpy(), cells),
        "Feature_Cutoff": np.repeat((history_dates[0] + pd.to_timedelta(origins - 1, unit="D")).to_numpy(), cells),
        DISTRICT: pd.Categorical(np.tile(np.repeat(districts, 24), len(targets)), categories=districts),
        "Hour": np.tile(np.arange(24, dtype=np.int8), len(targets) * len(districts)),
        "Day_of_Week_Number": np.repeat(targets.dayofweek.to_numpy(dtype=np.int8), cells),
        "Month": np.repeat(targets.month.to_numpy(dtype=np.int8), cells),
        "Is_Weekend": np.repeat((targets.dayofweek >= 5).astype(np.int8), cells),
        "Recent_7_Daily_Avg": np.repeat(previous_7, 24, axis=1).reshape(-1).astype(np.float32),
        "Recent_28_Daily_Avg": np.repeat(previous_28, 24, axis=1).reshape(-1).astype(np.float32),
        "Same_Hour_Avg": same_hour.reshape(-1).astype(np.float32),
        "Recent_Same_Hour_Avg": recent_hour.reshape(-1).astype(np.float32),
        "Same_Weekday_Hour_Avg": same_weekday.reshape(-1).astype(np.float32),
    })
    return frame


def add_hourly_features(hourly_counts):
    cube, dates, districts = _tensor(hourly_counts)
    targets = np.arange(56, len(dates))
    origins = targets // 7 * 7
    validation_index = int((VALIDATION_START - dates[0]).days)
    validation_mask = targets >= validation_index
    origins[validation_mask] = validation_index + (targets[validation_mask] - validation_index) // 7 * 7
    features = _feature_frame(cube, dates, districts, dates[targets], origins)
    features["Incident_Count"] = cube[targets].reshape(-1)
    return features


def _preprocessor():
    return ColumnTransformer([
        ("district", OneHotEncoder(handle_unknown="ignore", sparse_output=False, dtype=np.float32), [DISTRICT]),
        ("numeric", StandardScaler(), NUMERIC_FEATURES),
    ])


def build_hourly_models():
    estimators = {
        "Poisson Regression": PoissonRegressor(alpha=0.1, max_iter=500),
        "Random Forest": RandomForestRegressor(n_estimators=150, max_depth=12, min_samples_leaf=5, max_samples=0.35, random_state=42, n_jobs=2),
        "HistGradientBoosting": HistGradientBoostingRegressor(loss="poisson", learning_rate=0.05, max_iter=200, max_leaf_nodes=31, max_bins=127, min_samples_leaf=30, l2_regularization=0.1, early_stopping=False, random_state=42),
    }
    return {name: Pipeline([("preprocessor", _preprocessor()), ("model", estimator)]) for name, estimator in estimators.items()}


def calculate_metrics(actual, predicted):
    return float(mean_absolute_error(actual, predicted)), float(np.sqrt(mean_squared_error(actual, predicted)))


def evaluate_hourly_models(features):
    training = features.loc[features["Date"].le(TRAIN_END)]
    validation = features.loc[features["Date"].ge(VALIDATION_START)]
    if training.empty or validation.empty:
        raise ValueError("Both 2017–2025 training history and 2026 validation history are required.")
    rows = []
    mae, rmse = calculate_metrics(validation["Incident_Count"], validation["Same_Weekday_Hour_Avg"])
    rows.append({"Model": BASELINE_NAME, "Validation_MAE": mae, "Validation_RMSE": rmse, "Status": "OK"})
    candidates = build_hourly_models()
    for name in list(candidates):
        candidate = candidates.pop(name)
        try:
            with threadpool_limits(limits=2):
                candidate.fit(training[FEATURE_COLUMNS], training["Incident_Count"])
                predictions = np.clip(candidate.predict(validation[FEATURE_COLUMNS]), 0, None)
            mae, rmse = calculate_metrics(validation["Incident_Count"], predictions)
            rows.append({"Model": name, "Validation_MAE": mae, "Validation_RMSE": rmse, "Status": "OK"})
        except ValueError as exc:
            rows.append({"Model": name, "Validation_MAE": np.nan, "Validation_RMSE": np.nan, "Status": str(exc)[:140]})
        del candidate
        gc.collect()
    results = pd.DataFrame(rows).sort_values("Validation_MAE", kind="stable", na_position="last").reset_index(drop=True)
    best = results.loc[results["Status"].eq("OK"), "Model"].iloc[0]
    return results, best


def prepare_hourly_forecast(df, crime_name1, today=None):
    today = pd.Timestamp(today if today is not None else county_today()).normalize()
    eligible_dates = df.loc[df["Date"].lt(today), "Date"]
    if eligible_dates.empty:
        raise ValueError("There is no history strictly before today.")
    source_end = pd.Timestamp(df.attrs.get("history_end", eligible_dates.max())).normalize()
    history_end = min(source_end, today - pd.Timedelta(days=1))
    if history_end < VALIDATION_START:
        raise ValueError("2026 validation records are not yet available.")
    hourly = build_hourly_counts(df, crime_name1, history_end)
    features = add_hourly_features(hourly)
    results, best = evaluate_hourly_models(features)
    final_model = None
    if best != BASELINE_NAME:
        final_model = build_hourly_models()[best]
        with threadpool_limits(limits=2):
            final_model.fit(features[FEATURE_COLUMNS], features["Incident_Count"])
    cube, dates, districts = _tensor(hourly)
    future_dates = pd.date_range(today, periods=7)
    future = _feature_frame(cube, dates, districts, future_dates, np.full(7, len(dates)))
    if best == BASELINE_NAME:
        predictions = future["Same_Weekday_Hour_Avg"].to_numpy()
    else:
        with threadpool_limits(limits=2):
            predictions = final_model.predict(future[FEATURE_COLUMNS])
    future["Predicted_Incidents"] = np.clip(predictions, 0, None)
    if not np.isfinite(future["Predicted_Incidents"]).all():
        raise ValueError("The model returned non-finite predictions.")
    bundle = {
        "crime_name1": crime_name1, "today": today, "history_end": history_end,
        "best_model": best, "model_results": results, "hourly_forecast": future,
        "counts": cube, "dates": dates, "districts": districts,
        "training_start": TRAIN_START, "effective_training_start": features["Date"].min(),
        "training_end": TRAIN_END, "validation_start": VALIDATION_START,
        "validation_end": history_end, "training_rows": int(features["Date"].le(TRAIN_END).sum()),
        "validation_rows": int(features["Date"].ge(VALIDATION_START).sum()),
        "resolved_incident_conflicts": hourly.attrs["resolved_incident_conflicts"],
        "loaded_at": df.attrs.get("loaded_at", ""),
    }
    # 仅保留七天结果与紧凑数组 / Keep seven-day results and compact count arrays
    del features, hourly, final_model
    gc.collect()
    return bundle


def assign_window_risk(predicted, p60, p85):
    return "High" if predicted > p85 else "Elevated" if predicted > p60 else "Normal"


def predict_hourly_window(bundle, forecast_date, start_hour, end_hour):
    forecast_date = pd.Timestamp(forecast_date).normalize()
    if not bundle["today"] <= forecast_date <= bundle["today"] + pd.Timedelta(days=6):
        raise ValueError("Select a date from today through today + 6 days.")
    if not (isinstance(start_hour, (int, np.integer)) and isinstance(end_hour, (int, np.integer)) and 0 <= start_hour <= end_hour <= 23):
        raise ValueError("Select inclusive whole hours between 0 and 23.")
    future = bundle["hourly_forecast"]
    selected = future.loc[future["Date"].eq(forecast_date) & future["Hour"].between(start_hour, end_hour)].copy()
    result = selected.groupby(DISTRICT, observed=True)["Predicted_Incidents"].sum().reindex(bundle["districts"]).rename("Expected_Incidents").to_frame()
    window = bundle["counts"][:, :, start_hour:end_hour + 1].sum(axis=2)
    result["Incident_Probability"] = -np.expm1(-result["Expected_Incidents"])
    result["P60"] = np.quantile(window, 0.60, axis=0)
    result["P85"] = np.quantile(window, 0.85, axis=0)
    result["Recent_7_Window_Avg"] = window[-7:].mean(axis=0)
    result["Recent_28_Window_Avg"] = window[-28:].mean(axis=0)
    result["Same_Weekday_Window_Avg"] = window[bundle["dates"].dayofweek == forecast_date.dayofweek].mean(axis=0)
    result["Risk_Level"] = [assign_window_risk(p, p60, p85) for p, p60, p85 in zip(result["Expected_Incidents"], result["P60"], result["P85"])]
    result = result.reset_index().sort_values("Expected_Incidents", ascending=False).reset_index(drop=True)
    historical = pd.DataFrame(window, index=bundle["dates"], columns=bundle["districts"])
    historical.index.name = "Date"
    weekly = future.loc[future["Hour"].between(start_hour, end_hour)].groupby(["Date", DISTRICT], observed=True)["Predicted_Incidents"].sum().rename("Expected Incidents").reset_index()
    return {"district_forecast": result, "hourly_forecast": selected, "historical_window": historical, "weekly_forecast": weekly}
