# This script simultaneously controls the source meters and raspberry pi camera
# and links the data from the user-inputted IDCSubmersion.csv

# Necessary Libraries --------------------------------------------------------------------------------------------------
import xtralien
import pandas as pd
import threading
import cv2
import time
from queue import Queue
from picamera2 import Picamera2
import os

# Pre-Submersion -------------------------------------------------------------------------------------------------------
# read the csv
data = pd.read_csv("IDCSubmersion.csv")

# user must input the board ID of the board they are submerging, which will be matched with
# the data in IDCSubmersion.csv
ID = str(input("Enter the board ID of the board you are submerging: "))
submersion = data[data["board_id"] == ID]

# cancel by pressing any key
print("Press any key to cancel")

# potentially give option to select only 1 or 2?
cameras = 4

# potentially change device names to be more specific
source_meter_names = ["source_meter_1", "source_meter_2"]

# change
resolution = (8000, 8000)

# set to 1 frame per second
fps = 1

# raise an error if the selected board id isn't found
if submersion.empty:
    raise ValueError("Board not found in CSV")

# get the voltage level from the data frame
voltage = submersion["voltage"].values[0]


# Threading ------------------------------------------------------------------------------------------------------------

# source meter thread
def instrument_thread(device_name, device_index, data_queue, voltage, stop_event):

    with xtralien.Device(device_name) as device:

        while not stop_event.is_set():

            result = device.SMU[0].measure.iv(voltage)

            data_queue.put({"timestamp": time.time(), "device_index": device_index, "measurement": result})

            time.sleep(0.1)


# raspberry pi camera thread
def camera_thread(cam_index, stop_event):

    # initialize camera and start
    cam = Picamera2(cam_index)
    cam.start()

    os.makedirs(f"cam{cam_index}_frames", exist_ok=True)
    frame_index = 0

    window_name = f"Camera {cam_index}"

    frame_timestamps = []

    # continue recording unless stopped by keyboard
    while not stop_event.is_set():
        frame = cam.capture_array()

        # ensure frame is in color
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # save frame in correct resolution
        frame = cv2.resize(frame, resolution)

        frame_timestamps.append({"cam_index": cam_index, "frame_index": frame_index, "timestamp": time.time()})

        cv2.imwrite(f"cam{cam_index}_frames/frame_{frame_index:05d}.jpg", frame)
        frame_index += 1

        cv2.imshow(window_name, frame)

        # if q is pressed, stop
        if cv2.waitKey(1) & 0xFF == ord("q"):
            stop_event.set()
            break

    pd.DataFrame(frame_timestamps).to_csv(f"cam{cam_index}_timestamps.csv", index=False)
    
    cam.stop()
    cv2.destroyWindow(window_name)

# stop threading
stop_event = threading.Event()
data_queue = Queue()

# initialize source meter data
source_meter_data = []

# begin source meter thread
for i, device_name in enumerate(source_meter_names):
    threading.Thread(target=instrument_thread, args=(device_name, i, data_queue, voltage, stop_event), daemon=True).start()

# begin raspberry pi camera thread
camera_threads = []

# for all 4 cameras, start a thread
for cam_index in range(cameras):
    cam_thread = threading.Thread(target=camera_thread, args=(cam_index, stop_event), daemon=True)
    cam_thread.start()
    camera_threads.append(cam_thread)


# Queue ----------------------------------------------------------------------------------------------------------------
try:
    while not stop_event.is_set():
        while not data_queue.empty():
            entry = data_queue.get()
            source_meter_data.append(entry)
        time.sleep(0.05)

except KeyboardInterrupt:
    print("Cancelling...")
    stop_event.set()


for t in camera_threads:
    t.join(timeout=5)

# Saving data ----------------------------------------------------------------------------------------------------------

# write source meter data to csv
pd.DataFrame(source_meter_data).to_csv("source_meter_data.csv", index=False)
print("Saved source_meter_data.csv")

cv2.destroyAllWindows()