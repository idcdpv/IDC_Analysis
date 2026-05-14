# this script links the source meter data with each corresponding frame time-stamp
import pandas as pd

# read source meter data csv
source_data = pd.read_csv("source_meter_data.csv")
source_data["timestamp"] = source_data["timestamp"].astype(float)

# sort
source_data = source_data.sort_values("timestamp")

for cam_index in range(4):

    frames = pd.read_csv(f"cam{cam_index}_timestamps.csv")
    frames = frames.sort_values("timestamp")

    linked_devices = []

    # for each device, find the closest source meter reading per frame
    for device_index, device_data in source_data.groupby("device_index"):
        device_data = device_data.sort_values("timestamp").reset_index(drop=True)

        merged = pd.merge_asof(frames, device_data[["timestamp", "measurement"]], on="timestamp", direction="nearest",
            suffixes=("_frame", "_source"))

        merged["device_index"] = device_index

        merged = merged.rename(columns={"timestamp": "frame_timestamp"})

        closest_source_times = device_data["timestamp"].iloc[
            (device_data["timestamp"].values[:, None] - frames["timestamp"].values).argmin(axis=0)]

        merged["source_timestamp"] = closest_source_times.values
        merged["time_delta_ms"] =(abs(merged["frame_timestamp"] - merged["source_timestamp"]) * 1000)

        linked_devices.append(merged)

    result = pd.concat(linked_devices, ignore_index=True)
    result = result.sort_values(["frame_index", "device_index"])

    result.to_csv(f"cam{cam_index}_linked.csv", index=False)
    print(f"Saved cam{cam_index}_linked.csv")