from threading import Lock

import streamlit as st

from data_service import CACHE_TTL_SECONDS, load_forecast_data
from model import prepare_hourly_forecast

# 限制并发训练与内存占用 / Limit concurrent training and memory use
_TRAINING_LOCK = Lock()


@st.cache_resource(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner=False)
def get_forecast_bundle(crime_name1, today_string):
    with _TRAINING_LOCK:
        data = load_forecast_data(crime_name1, today_string)
        return prepare_hourly_forecast(data, crime_name1, today=today_string)
