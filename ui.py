import streamlit as st

from data_service import CrimeDataError, DATASET_URL, clear_remote_caches


def setup_page(title, icon):
    st.set_page_config(page_title=title, page_icon=icon, layout="wide", initial_sidebar_state="expanded")
    st.title(title)
    st.sidebar.page_link("Home.py", label="Home", icon="🏠")
    if st.sidebar.button("Refresh online data", help="Clear the shared in-memory data and model results, then request the API again."):
        clear_remote_caches()
        from forecast_service import get_forecast_bundle
        get_forecast_bundle.clear()
        st.session_state.pop("forecast_key", None)
        st.session_state.pop("forecast_summary", None)
        st.rerun()
    st.sidebar.caption("Montgomery County, Maryland · America/New_York")
    st.sidebar.markdown(f"[Official data source]({DATASET_URL})")


def load_with_message(loader, *args):
    try:
        with st.spinner("Loading current records from Montgomery County Open Data…"):
            df = loader(*args)
    except CrimeDataError as exc:
        st.error(str(exc))
        st.info("This page requires the online source. Use Refresh online data to retry.")
        st.stop()
    if df.empty:
        st.info("No records are available for this selection.")
        st.stop()
    return df


def source_caption(df):
    stamp = df.attrs.get("loaded_at", "")
    st.caption(f"Source: Montgomery County Open Data · Retrieved {stamp[:19].replace('T', ' ')} ET. Counts may change when source records are revised.")
