import paramiko
import threading
import time
import os
from datetime import date
import xtralien
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from queue import Queue


# --- 1. Configuration & Mapping ---
devices = [
    {"host": "raspberrypi.local",  "user": "pi", "pass": "password", "folders": ["Cam_1", "Cam_2"]},
    {"host": "raspberrypi2.local", "user": "pi", "pass": "password", "folders": ["Cam_3", "Cam_4"]}
]

mapping = {
    "COM4": {"pi": devices[0], "SMU1": 0, "SMU2": 1},
    "COM5": {"pi": devices[1], "SMU1": 0, "SMU2": 1}
}

source_meter_names = ["COM4", "COM5"]


# --- 2. Setup & Input ---
try:
    board_id = str(input("Enter the board ID: "))
    while True:
        try:
            voltage = float(input("Enter the voltage for the SMU (0 to 5V): "))
            if 0.0 <= voltage <= 5.0:
                break
            print("Error: Voltage must be between 0 and 5V.")
        except ValueError:
            print("Error: Invalid numerical value.")

    while True:
        try:
            timelapse_ms = int(input("Enter image capture interval in milliseconds (e.g. 1000 = 1/sec): "))
            if timelapse_ms > 0:
                break
            print("Error: Interval must be a positive integer.")
        except ValueError:
            print("Error: Invalid integer value.")

except Exception as e:
    print(f"Setup Error: {e}")
    exit()



# --- 3. Remote Control Functions ---
def start_remote_cameras(device, board_id, timelapse_ms):
    f1, f2 = device["folders"]
    s_idx1, s_idx2 = (3, 4) if "2" in device["host"] else (1, 2)
    today = date.today().strftime("%Y%m%d")

    cmd = (
        f"mkdir -p /home/pi/{f1} /home/pi/{f2} && sleep 1 && "
        f"nohup /usr/bin/rpicam-still --camera 0 -t 0 --timelapse {timelapse_ms} -n "
        f"-o '/home/pi/{f1}/{board_id}_U{s_idx1}_{today}_timeseries_%05d.jpg' "
        f"> /home/pi/cam0_debug.txt 2>&1 & "
        f"nohup /usr/bin/rpicam-still --camera 1 -t 0 --timelapse {timelapse_ms} -n "
        f"-o '/home/pi/{f2}/{board_id}_U{s_idx2}_{today}_timeseries_%05d.jpg' "
        f"> /home/pi/cam1_debug.txt 2>&1 & "
        f"disown -a"
    )

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(device["host"], username=device["user"], password=device["pass"])
        client.exec_command(cmd)
        client.close()
        print(f"[PI] Cameras started on {device['host']} ({timelapse_ms}ms interval)")
    except Exception as e:
        print(f"SSH Start Error on {device['host']}: {e}")

def stop_specific_camera(pi_device, cam_index):

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(pi_device["host"], username=pi_device["user"], password=pi_device["pass"])
        client.exec_command(f"pkill -f 'rpicam-still --camera {cam_index}'")
        client.close()
        print(f"  [PI] Stopped camera {cam_index} on {pi_device['host']}")
    except Exception as e:
        print(f"  [PI ERROR] Could not stop camera {cam_index}: {e}")

def stop_all_cameras(device):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(device["host"], username=device["user"], password=device["pass"])
        client.exec_command("pkill -f rpicam-still")
        client.close()
        print(f"[PI] All cameras stopped on {device['host']}")
    except Exception as e:
        print(f"[PI ERROR] Could not stop cameras on {device['host']}: {e}")

# --- 4. Instrument Thread ---
def instrument_thread(device_name, data_queue, volt, stop_event):
    pi_info = mapping[device_name]["pi"]
    failed_chans = set()

    try:
        with xtralien.Device(device_name) as device:
            device.smu1.set.enabled(True)
            device.smu2.set.enabled(True)
            exp_start = time.time()

            while not stop_event.is_set():
                loop_start = time.time()
                elapsed = round(loop_start - exp_start, 2)

                row = {"Seconds": elapsed, "Meter": device_name,
                       "SMU1_I": None, "SMU1_V": None,
                       "SMU2_I": None, "SMU2_V": None}

                for chan in ["SMU1", "SMU2"]:
                    if chan in failed_chans:
                        continue

                    smu = getattr(device, chan.lower())
                    res = smu.oneshot(volt)

                    if isinstance(res, str) or abs(res[0, 1]) >= 0.195:
                        print(f"\n[!] OVERCURRENT: {device_name} {chan} hit 200mA at {elapsed}s")
                        smu.set.enabled(False)
                        cam_id = mapping[device_name][chan]
                        threading.Thread(
                            target=stop_specific_camera,
                            args=(pi_info, cam_id),
                            daemon=True
                        ).start()
                        failed_chans.add(chan)
                    else:
                        row[f"{chan}_I"] = res[0, 1]
                        row[f"{chan}_V"] = res[0, 0]

                # Only log if at least one channel is still active
                if any(row[k] is not None for k in ["SMU1_I", "SMU2_I"]):
                    data_queue.put(row)

                time.sleep(max(0, 1.0 - (time.time() - loop_start)))

            device.smu1.set.enabled(False)
            device.smu2.set.enabled(False)

    except Exception as e:
        print(f"Thread Error on {device_name}: {e}")

# --- 5. Execution & Plotting ---
stop_event = threading.Event()
data_queue = Queue()
source_meter_data = []

for d in devices:
    threading.Thread(
        target=start_remote_cameras,
        args=(d, board_id, timelapse_ms),
        daemon=True
    ).start()

instrument_threads = []
for dev_name in source_meter_names:
    t = threading.Thread(
        target=instrument_thread,
        args=(dev_name, data_queue, voltage, stop_event),
        daemon=True
    )
    t.start()
    instrument_threads.append(t)

# Plotting setup
fig, axs = plt.subplots(2, 2, figsize=(10, 8), sharex=True)
fig.suptitle(f"Real-time Monitoring: Board {board_id}")
ax_list = axs.flatten()
lines = [ax.plot([], [], 'b-')[0] for ax in ax_list]
data_bins = [([], []) for _ in range(4)]

sensor_labels = ["COM4 SMU1 (U1)", "COM4 SMU2 (U2)", "COM5 SMU1 (U3)", "COM5 SMU2 (U4)"]
for i, ax in enumerate(ax_list):
    ax.set_title(sensor_labels[i])
    ax.set_ylabel("Current (A)")
    ax.set_xlabel("Time (s)")
    ax.grid(True)

def update_plot(frame):
    while not data_queue.empty():
        item = data_queue.get()
        source_meter_data.append(item)

        base = 0 if item["Meter"] == "COM4" else 2

        if item["SMU1_I"] is not None:
            data_bins[base][0].append(item["Seconds"])
            data_bins[base][1].append(item["SMU1_I"])

        if item["SMU2_I"] is not None:
            data_bins[base + 1][0].append(item["Seconds"])
            data_bins[base + 1][1].append(item["SMU2_I"])

    for i, line in enumerate(lines):
        if data_bins[i][0]:
            line.set_data(data_bins[i][0], data_bins[i][1])
            ax_list[i].relim()
            ax_list[i].autoscale_view()
    return lines

def on_close(event):
    print("\nWindow closed — hard stopping all SMUs and cameras...")
    stop_event.set()

fig.canvas.mpl_connect('close_event', on_close)
ani = FuncAnimation(fig, update_plot, interval=500, cache_frame_data=False)
plt.tight_layout(rect=[0, 0.03, 1, 0.95])
plt.show()

# --- 6. Final Cleanup ---
for t in instrument_threads:
    t.join(timeout=5)

# Drain any remaining data from the queue before saving
print("Finalizing data collection...")
while not data_queue.empty():
    source_meter_data.append(data_queue.get())

# Stop all cameras and wait for SSH commands to complete
camera_stop_threads = []
for d in devices:
    t = threading.Thread(target=stop_all_cameras, args=(d,), daemon=True)
    t.start()
    camera_stop_threads.append(t)

for t in camera_stop_threads:
    t.join(timeout=3)

if source_meter_data:
    current_date = date.today().strftime("%Y%m%d")
    filename = f"{board_id}_{current_date}_electricaldata.csv"
    save_path = os.path.join(
        r"C:\Users\ja917984\Documents\Automated_IDC_Analysis\electrical_data",
        filename
    )
    pd.DataFrame(source_meter_data).to_csv(save_path, index=False)
    print(f"Data saved to {filename}")