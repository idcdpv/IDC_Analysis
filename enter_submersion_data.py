# This script takes user input for upcoming IDC submersions, including the
# board ID, voltage level, solution type and concentration, and writes this
# data to a csv for further use

import pandas as pd
import os

# create an empty data frame with the necessary columns
image_data=pd.DataFrame(columns=["board_id","sensor","voltage","solution","concentration (mM)","pH"])

# use IDCSubmersion.csv as the file to add the data to
data_file_path="IDCSubmersion.csv"

# create an initial CSV file if it doesn't exist
if not os.path.exists(data_file_path):
    image_data.to_csv(data_file_path, index=False)

# writes board ID, voltage level, solution + concentration to a csv using user inputted data
def get_image_names_and_data(data_file_path):

    board_id=str(input("Enter Board ID (Format: 00_00_0000) :\n"))

    # initialize voltage level as 0 for safety
    voltage_level=0

    # input voltage level choice
    #while (voltage_level != 3) & (voltage_level != 5):
    #    voltage_level=int(input("\nChoose voltage level\n Must be 3 or 5:\n"))

    # input solution type choice
    solution_choice=int(input("\nChoose one of the following solutions:\n"
                              "(1) DI Water\n"
                              "(2) Adipic Acid\n"
                              "(3) Succinic\n"
                              "Type 1, 2, or 3:\n"))

    # set solution type based on choice
    if solution_choice==1:
        solution_type="DI Water"
    elif solution_choice==2:
        solution_type="Adipic Acid"
    elif solution_choice==3:
        solution_type="Succinic"

    # input concentration
    solution_concentration=float(input("\nEnter the solution concentration:\n"))

    # (may remove concentration in the future)
    #solution_concentration_choice = int(input("\nChoose one of the following concentrations:\n"
                               # "(1) 1.24 mM\n"
                               # "(2) 20 mM\n"
                               # "(3) 0.388\n"
                               # "(4) 3.6\n"
                               # "(5) 1.425\n"
                               # "(6) 0.712\n"
                               # "(7) 1.24\n"
                               # "(8) Solution is DI Water"
                               # "Type 1, 2, 3, 4, 5, 6, 7, or 8\n"))

    #if solution_concentration_choice == 1:
        #solution_type = "DI Water"
    #elif solution_concentration_choice == 2:
       # solution_type = "Adipic Acid"
    #elif solution_concentration_choice == 3:
        #solution_type = "Succinic"

    # initialize pH
    pH=-1

    # pH range
    while (pH <= 0) | (pH >= 14):
        pH=int(input("\nEnter the pH:\n"))

    # create list of sensors
    sensors = ["U1", "U2", "U3", "U4"]

    # store information in IDCSubmersion.csv
    for sensor_name in sensors:

        # board information dictionary
        info = {"board_id": [board_id], "sensor": [sensor_name], "voltage": [voltage_level], "solution": [solution_type],
                "concentration (mM)": [solution_concentration], "pH": [pH]}

        # put new data into a data frame
        new_data=pd.DataFrame(info)

        # write new row to csv
        new_data.to_csv(data_file_path, mode="a", header=False, index=False)


get_image_names_and_data(data_file_path)