import os
import glob
import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketsApi
from influxdb_client.client.write_api import SYNCHRONOUS
import subprocess
from datetime import datetime
from multiprocessing import Pool, cpu_count, freeze_support
from tqdm import tqdm

# Config
DEFAULT_INPUT_FOLDER = r"C:\Users\Administrator\Desktop\HST Translator\data"  # Relative to "Hamid"
TRENDCONVERT_PATH = r"C:\Users\Administrator\Desktop\HST Translator\trendconvert\trendconvert.py"
SHARED_OUTPUT = r"Y:\\"  # VM #2 shared - no local save

def get_user_input(prompt, default=None):
    user_input = input(prompt).strip()
    return user_input if user_input else default

def get_input_folders():
    use_default = get_user_input(f"Use default input folder ({DEFAULT_INPUT_FOLDER})? (y/n): ", "y").lower()
    if use_default == 'y':
        return [DEFAULT_INPUT_FOLDER]
    
    input_type = get_user_input("Enter 's' for single folder or 't' for text file with multiple folders: ").lower()
    if input_type == 's':
        folder = get_user_input("Enter the input folder path: ")
        return [folder]
    elif input_type == 't':
        text_file = get_user_input("Enter the text file path containing folder paths: ")
        with open(text_file, 'r') as f:
            folders = [line.strip() for line in f if line.strip()]
        return folders
    else:
        print("Invalid choice. Exiting.")
        exit(1)

def process_hst_to_csv(args):
    hst_file = args
    cmd = ["python", TRENDCONVERT_PATH, hst_file, "-o", "csv", "-s", "-outdir", SHARED_OUTPUT]
    try:
        result = subprocess.run(cmd, capture_output=False, text=True, check=True)
        print(f"✓ Processed {os.path.basename(hst_file)}")
        print(f"  ✓ HST parsing completed successfully")
        
        base_name = os.path.splitext(os.path.basename(hst_file))[0]
        csv_file = os.path.join(SHARED_OUTPUT, f"{base_name}.csv")
        if os.path.exists(csv_file):
            # Rename 'Time' to 'Timestamp'
            df = pd.read_csv(csv_file)
            df.rename(columns={'Time': 'Timestamp'}, inplace=True)
            df.to_csv(csv_file, index=False)
            print("  ✓ Renamed 'Time' to 'Timestamp' in CSV")
            
            size_mb = os.path.getsize(csv_file) / 1024 / 1024
            print(f"  → Saved to shared: {os.path.basename(csv_file)} ({size_mb:.1f} MB)")
            return csv_file
        return None
    except subprocess.CalledProcessError as e:
        print(f"✗ ERROR {os.path.basename(hst_file)}: {e}")
        return None

if __name__ == '__main__':
    freeze_support()
    
    print("🚀 Starting HST to CSV on VM #1 (saves to VM #2 shared)")
    
    # User prompts for inputs (outputs fixed to shared)
    input_folders = get_input_folders()
    
    # Collect all HSTs
    tasks = []
    for input_folder in input_folders:
        print(f"\nProcessing folder: {input_folder}")
        hst_files = glob.glob(os.path.join(input_folder, "*.hst"))
        print(f"📋 Found {len(hst_files)} HST files")
        tasks.extend(hst_files)
    
    # Parallel conversion to shared
    if tasks:
        print(f"\nParallel processing {len(tasks)} HST files...")
        with Pool(processes=cpu_count() - 1) as pool:
            csv_files = list(tqdm(pool.imap(process_hst_to_csv, tasks), total=len(tasks), desc="Converting HSTs"))
        csv_files = [c for c in csv_files if c]
    
    print("\n🎉 CSVs saved to VM #2 shared folder. Run inserter on VM #2.")