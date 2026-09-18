from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 在线来源 / Online source
API_ROOT = "https://data.montgomerycountymd.gov"
DATASET_ID = "icn6-v9z3"
API_URL = f"{API_ROOT}/resource/{DATASET_ID}.csv"
JSON_URL = f"{API_ROOT}/resource/{DATASET_ID}.json"
METADATA_URL = f"{API_ROOT}/api/views/{DATASET_ID}.json"
DATASET_URL = f"{API_ROOT}/Public-Safety/Crime/{DATASET_ID}/about_data"
CACHE_TTL_SECONDS = 3600
API_PAGE_SIZE = 50000
OFFENSE_NAME = "Theft From Motor Vehicle"
CRIME_TYPES = ["All", "Crime Against Person", "Crime Against Property", "Crime Against Society"]
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
REMOTE_COLUMN_MAP = {
    "incident_id": "Incident ID", "start_date": "Start_Date_Time",
    "crimename1": "Crime Name1", "crimename2": "Crime Name2", "crimename3": "Crime Name3",
    "district": "Police District Name", "zip_code": "Zip Code", "place": "Place",
    "latitude": "Latitude", "longitude": "Longitude", "date": "Dispatch Date / Time",
}
GENERAL_FIELDS = tuple(k for k in REMOTE_COLUMN_MAP if k != "date")
TARGET_FIELDS = tuple(REMOTE_COLUMN_MAP)
FORECAST_FIELDS = ("incident_id", "start_date", "crimename1", "district")
ZIP_AREA_PROFILE = {
    **dict.fromkeys("20812 20815 20816 20817 20818 20833 20838 20841 20842 20854 20862 20871 20882 20896".split(), "High"),
    **dict.fromkeys("20814 20832 20837 20850 20851 20852 20853 20855 20861 20866 20868 20872 20874 20876 20878 20879 20880 20895 20901 20902 20905 20910".split(), "Mix"),
    **dict.fromkeys("20839 20877 20886 20903 20904 20906 20912".split(), "Low/Mid"),
}


class CrimeDataError(RuntimeError):
    pass


def county_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def create_http_session() -> requests.Session:
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "MontgomeryCrimeDashboard/2.0", "Accept": "text/csv"})
    token = os.getenv("SOCRATA_APP_TOKEN", "").strip()
    if not token:
        try:
            token = str(st.secrets.get("SOCRATA_APP_TOKEN", "")).strip()
        except (FileNotFoundError, KeyError):
            token = ""
    if token:
        session.headers["X-App-Token"] = token
    return session


def _get(session, url, params=None):
    try:
        response = session.get(url, params=params, timeout=(10, 90))
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f" (HTTP {status})" if status else ""
        raise CrimeDataError(f"Montgomery County Open Data is unavailable{detail}. Check the connection and retry.") from exc


def _metadata(session):
    try:
        metadata = _get(session, METADATA_URL).json()
        if "columns" not in metadata:
            raise ValueError("Missing schema")
        return metadata
    except (ValueError, TypeError) as exc:
        raise CrimeDataError("The online dataset metadata could not be validated.") from exc


def _where(start: date | None = None, end_exclusive: date | None = None, crime: str | None = None):
    conditions = ["start_date IS NOT NULL", "incident_id IS NOT NULL", "crimename1 IS NOT NULL", "crimename1 != 'Crime Against Not a Crime'"]
    if start is not None:
        conditions.append(f"start_date >= '{start.isoformat()}T00:00:00'")
    if end_exclusive is not None:
        conditions.append(f"start_date < '{end_exclusive.isoformat()}T00:00:00'")
    if crime and crime != "All":
        if crime not in CRIME_TYPES:
            raise ValueError("Unsupported crime type.")
        conditions.append(f"crimename1 = '{crime}'")
    return " AND ".join(conditions)


def query_json(select, where, group=None, order=None):
    params = {"$select": select, "$where": where, "$limit": 50000}
    if group:
        params["$group"] = group
    if order:
        params["$order"] = order
    with create_http_session() as session:
        try:
            rows = _get(session, JSON_URL, params).json()
        except ValueError as exc:
            raise CrimeDataError("The online API returned an invalid response.") from exc
    if not isinstance(rows, list):
        raise CrimeDataError("The online API did not return records.")
    return rows


# 只在内存解析网络响应 / Parse network bytes only in memory
# 分页中更新时停止，避免混合版本 / Reject updates during pagination

def fetch_remote_rows(fields, where):
    pages = []
    raw_rows = 0
    with create_http_session() as session:
        metadata = _metadata(session)
        schema = {c["fieldName"] for c in metadata["columns"]}
        missing = set(fields) - schema
        if missing:
            raise CrimeDataError("Online schema is missing: " + ", ".join(sorted(missing)))
        version = metadata.get("rowsUpdatedAt")
        offset = 0
        while True:
            params = {"$select": ",".join(fields), "$where": where, "$order": ":id", "$limit": API_PAGE_SIZE, "$offset": offset}
            response = _get(session, API_URL, params)
            try:
                page = pd.read_csv(BytesIO(response.content), dtype="string")
            except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
                raise CrimeDataError("The online CSV response could not be parsed.") from exc
            if set(fields) - set(page.columns):
                raise CrimeDataError("The online response is missing requested fields.")
            if page.empty:
                break
            page_rows = len(page)
            raw_rows += page_rows
            # 逐页清洗以降低峰值内存 / Clean each page to reduce peak memory
            pages.append(clean_dataframe(page.loc[:, list(fields)]))
            del page, response
            if page_rows < API_PAGE_SIZE:
                break
            offset += page_rows
        if _metadata(session).get("rowsUpdatedAt") != version:
            raise CrimeDataError("The source changed during loading. Please retry to obtain a consistent result.")
    result = pd.concat(pages, ignore_index=True) if pages else clean_dataframe(pd.DataFrame(columns=fields))
    del pages
    for col in ("Crime Name1", "Crime Name2", "Crime Name3", "Police District Name", "Zip Code", "Place", "Day_of_Week", "Area_Profile"):
        if col in result:
            result[col] = result[col].astype("category")
    result.attrs.update(source_version=version, loaded_at=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                        data_source="Montgomery County Open Data API", raw_rows=raw_rows,
                        latest_data_date=result["Date"].max())
    return result


# 保留罪名明细；仅在统计时去重 / Preserve offense rows; deduplicate within summaries

def clean_dataframe(raw):
    attrs = dict(raw.attrs)
    df = raw.rename(columns=REMOTE_COLUMN_MAP).copy()
    required = {"Incident ID", "Start_Date_Time", "Crime Name1", "Police District Name"}
    if required - set(df.columns):
        raise CrimeDataError("Required incident fields are missing.")
    for col in df.columns:
        if col not in ("Start_Date_Time", "Dispatch Date / Time", "Latitude", "Longitude"):
            df[col] = df[col].astype("string").str.strip().str.replace(r"\s+", " ", regex=True).replace("", pd.NA)
    df["Start_Date_Time"] = pd.to_datetime(df["Start_Date_Time"], format="mixed", errors="coerce")
    df = df.loc[df["Incident ID"].notna() & df["Start_Date_Time"].notna() & df["Crime Name1"].notna() & df["Crime Name1"].ne("Crime Against Not a Crime")].copy()
    dt = df["Start_Date_Time"].dt
    df["Date"] = dt.normalize()
    for name, values, dtype in [("Year", dt.year, "int16"), ("Month", dt.month, "int8"), ("Hour", dt.hour, "int8"), ("Day_of_Week_Number", dt.dayofweek, "int8")]:
        df[name] = values.astype(dtype)
    df["Day_of_Week"] = dt.day_name().astype("category")
    df["Is_Weekend"] = df["Day_of_Week_Number"].ge(5)
    for col in ("Crime Name1", "Crime Name2", "Crime Name3", "Police District Name", "Place"):
        if col in df:
            df[col] = df[col].fillna("Unknown").astype("category")
    if "Zip Code" in df:
        df["Zip Code"] = df["Zip Code"].str.extract(r"^(\d{5})(?:\.0|[-\s]\d{4})?$", expand=False).fillna("Unknown").astype("category")
        df["Area_Profile"] = df["Zip Code"].astype("string").map(ZIP_AREA_PROFILE).fillna("Unknown").astype("category")
    if {"Latitude", "Longitude"} <= set(df.columns):
        for col in ("Latitude", "Longitude"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
        df["Valid_Coordinates"] = df["Latitude"].between(38.90, 39.40) & df["Longitude"].between(-77.60, -76.80)
    if "Dispatch Date / Time" in df:
        df["Dispatch Date / Time"] = pd.to_datetime(df["Dispatch Date / Time"], format="mixed", errors="coerce")
    df.attrs.update(attrs, data_source="Montgomery County Open Data API", raw_rows=len(raw), latest_data_date=df["Date"].max())
    return df.reset_index(drop=True)


# 全局共享内存，不写磁盘 / Shared RAM only; no disk persistence
@st.cache_resource(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner=False)
def load_and_clean_data():
    return fetch_remote_rows(GENERAL_FIELDS, _where(end_exclusive=county_today() + timedelta(days=1)))


@st.cache_resource(ttl=CACHE_TTL_SECONDS, max_entries=2, show_spinner=False)
def load_targeted_vehicle_theft_data(baseline_year=2024, comparison_year=2025):
    last_year = county_today().year - 1
    if not (2017 <= int(baseline_year) < int(comparison_year) <= last_year):
        raise ValueError("Choose two complete calendar years, with the baseline first.")
    where = _where() + f" AND crimename2 = '{OFFENSE_NAME}' AND (" + " OR ".join(
        f"(start_date >= '{year}-01-01T00:00:00' AND start_date < '{year + 1}-01-01T00:00:00')"
        for year in (int(baseline_year), int(comparison_year))
    ) + ")"
    return fetch_remote_rows(TARGET_FIELDS, where)


@st.cache_resource(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner=False)
def load_forecast_data(crime_name1, today_string):
    today = date.fromisoformat(today_string)
    where = _where(date(2017, 1, 1), today, crime_name1)
    df = fetch_remote_rows(FORECAST_FIELDS, where)
    status = query_json("max(start_date) as latest", _where(date(2017, 1, 1), today))
    if not status or not status[0].get("latest"):
        raise CrimeDataError("No complete historical dates are available before today.")
    df.attrs["history_end"] = pd.Timestamp(status[0]["latest"]).normalize()
    df.attrs["selected_crime"] = crime_name1
    return df


@st.cache_resource(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner=False)
def get_remote_status():
    rows = query_json("count(*) as row_count,count(distinct incident_id) as incidents,min(start_date) as earliest,max(start_date) as latest", _where(end_exclusive=county_today() + timedelta(days=1)))
    if not rows:
        raise CrimeDataError("No online dataset status was returned.")
    return rows[0]


def clear_remote_caches():
    for loader in (load_and_clean_data, load_targeted_vehicle_theft_data, load_forecast_data, get_remote_status):
        loader.clear()
