import argparse

from data_service import CRIME_TYPES, county_today, load_forecast_data
from model import predict_hourly_window, prepare_hourly_forecast


# 手动在线检查，不读写数据文件 / Manual online check; no data files

def main():
    parser = argparse.ArgumentParser(description="Run the hourly forecasting pipeline against the online county API.")
    parser.add_argument("--crime", choices=CRIME_TYPES, default="Crime Against Property")
    args = parser.parse_args()
    today = county_today().isoformat()
    print("Loading eligible online history…", flush=True)
    data = load_forecast_data(args.crime, today)
    bundle = prepare_hourly_forecast(data, args.crime, today)
    result = predict_hourly_window(bundle, today, 18, 22)
    print("History through:", bundle["history_end"])
    print("Selected model:", bundle["best_model"])
    print(bundle["model_results"].to_string(index=False))
    print(result["district_forecast"].round(4).to_string(index=False))
    assert bundle["history_end"] < bundle["today"]
    assert result["district_forecast"]["Incident_Probability"].between(0, 1).all()
    print("Online forecast check passed. No dataset or model was saved.")


if __name__ == "__main__":
    main()
