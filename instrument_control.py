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

# --- Pre-Submersion Setup ---
devices = [{"host": "raspberrypi.local", "user": "pi", "pass": "password", "folders": ["Cam_1", "Cam_2"]},
           {"host": "raspberrypi2.local", "user": "pi", "pass": "password", "folders": ["Cam_3", "Cam_4"]}]

source_meter_names = ["COM4", "COM5"]
data_csv_path = "IDCSubmersion.csv"

try:
    data = pd.read_csv(data_csv_path)
    board_id = str(input("Enter the board ID: "))
    submersion = data[data["board_id"] == board_id]

    if submersion.empty:
        raise ValueError("Board ID not found in CSV.")

    # --- New Interactive Voltage Prompt ---
    while True:
        try:
            voltage = float(input("Enter the voltage for the SMU (0 to 5V): "))
            if 0.0 <= voltage <= 5.0:
                break # Valid voltage entered, exit the loop
            else:
                print("Error: Voltage must be strictly between 0 and 5V. Try again.")
        except ValueError:
            print("Error: Invalid format. Please enter a numerical value (e.g., 3.3).")

except Exception as e:
    print(f"Setup Error: {e}")
    exit()

# --- Camera Control ---
def start_remote_cameras(device, board_id):
    f1, f2 = device["folders"]
    s_idx1, s_idx2 = (3, 4) if "2" in device["host"] else (1, 2)
    
    # Naming: boardId_sensorNumber_seconds_date
    cmd = (f"mkdir -p /home/pi/{f1} /home/pi/{f2} && sleep 1 && "
       f"nohup /usr/bin/rpicam-still --camera 0 -t 0 --timelapse 1000 -n "
       f"-o /home/pi/{f1}/{board_id}_U{s_idx1}_$(date +%Y%m%d)_timeseries_%05d.jpg > /home/pi/cam0_debug.txt 2>&1 & "
       f"nohup /usr/bin/rpicam-still --camera 1 -t 0 --timelapse 1000 -n "
       f"-o /home/pi/{f2}/{board_id}_U{s_idx2}_$(date +%Y%m%d)_timeseries_%05d.jpg > /home/pi/cam1_debug.txt 2>&1 & "
       f"disown -a")

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(device["host"], username=device["user"], password=device["pass"])
        client.exec_command(cmd)
        client.close()
    except Exception as e:
        print(f"SSH Error on {device['host']}: {e}")

def stop_remote_cameras(device):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(device["host"], username=device["user"], password=device["pass"])
        client.exec_command("pkill rpicam-still")
        client.close()
    except: pass


# instrument thread
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

# --- Execution ---
stop_event = threading.Event()
data_queue = Queue()
source_meter_data = []

for d in devices:
    threading.Thread(target=start_remote_cameras, args=(d, board_id)).start()

instrument_threads = []
for dev_name in source_meter_names:
    t=threading.Thread(target=instrument_thread, args=(dev_name, data_queue, voltage, stop_event), daemon=True)
    t.start()
    instrument_threads.append(t)

# --- Plotting & Real-time UI ---
fig, axs = plt.subplots(2, 2, figsize=(10, 8), sharex=True)
fig.suptitle(f"Real-time Monitoring: Board {board_id}")
ax_list = axs.flatten()
lines = []
data_bins = [([], []) for _ in range(4)] 

for i, ax in enumerate(ax_list):
    line, = ax.plot([], [], 'b-')
    lines.append(line)
    ax.set_title(f"Sensor {i+1}")
    ax.set_ylabel("Current (A)")
    # This sets a window of +/- 50 microamps
    #ax.set_ylim(-0.001, 0.001)

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

ani = FuncAnimation(fig, update_plot, interval=500, cache_frame_data=False)
plt.tight_layout(rect=[0, 0.03, 1, 0.95])
plt.show() 

# --- Final Cleanup ---
print("\nShutting down...")
stop_event.set()

for t in instrument_threads:
    t.join(timeout=3.0)

def shutdown_smu(device_name, thread):
    if thread.is_alive():
        print(f"Thread for {device_name} still running, forcing SMU shutdown...")
        try:
            with xtralien.Device(device_name) as device:
                device.smu1.set.enabled(False)
                device.smu2.set.enabled(False)
                print(f"SMUs disabled on {device_name}")
        except Exception as e:
            print(f"Could not disable SMUs on {device_name}: {e}")
    else:
        print(f"SMUs on {device_name} shut down cleanly.")

for dev_name, thread in zip(source_meter_names, instrument_threads):
    shutdown_smu(dev_name, thread)

for d in devices:
    stop_remote_cameras(d)

if source_meter_data:
    current_date=date.today().strftime("%Y%m%d")
    filename = f"{board_id}_{current_date}_electricaldata.csv"
    file_path = os.path.join(r"C:\Users\ja917984\Documents\Automated_IDC_Analysis\electrical_data", filename)
    pd.DataFrame(source_meter_data).to_csv(file_path, index=False)
    print(f"Electrical data saved to {filename}")
