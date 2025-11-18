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
DEFAULT_INPUT_FOLDER = r"D:\khayyamian\Hamid\data"
TRENDCONVERT_PATH = r"D:\khayyamian\Hamid\trendconvert\trendconvert.py"
DEFAULT_OUTPUT_FOLDER = r"D:\khayyamian\Hamid\output_csvs"
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "Q0Zo8Wcc_4Tn3apXQBjCv2ME7GVV9LPLURByqbDuZR2_orPMxRA1reNsiKlJFYdCkadgn7hZ4LiGe2VDERq5TA=="
INFLUX_ORG = "khayyamian"
INFLUX_BUCKET = "PGDP"  # Single bucket for all data

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

def get_output_config(input_folders):
    use_default = get_user_input(f"Use default output folder ({DEFAULT_OUTPUT_FOLDER})? (y/n): ", "y").lower()
    if use_default == 'y':
        os.makedirs(DEFAULT_OUTPUT_FOLDER, exist_ok=True)
        return 'default', DEFAULT_OUTPUT_FOLDER
    
    output_type = get_user_input("Enter 's' for single custom output folder or 'p' for 'output' folder in each input folder: ").lower()
    if output_type == 's':
        folder = get_user_input("Enter the custom output folder path: ")
        os.makedirs(folder, exist_ok=True)
        return 'single', folder
    elif output_type == 'p':
        return 'per_folder', None
    else:
        print("Invalid choice. Exiting.")
        exit(1)

def process_hst_to_csv(args):
    hst_file, output_folder = args
    cmd = ["python", TRENDCONVERT_PATH, hst_file, "-o", "csv", "-s", "-outdir", output_folder]
    try:
        result = subprocess.run(cmd, capture_output=False, text=True, check=True)
        print(f"✓ Processed {os.path.basename(hst_file)}")
        print(f"  ✓ HST parsing completed successfully")
        
        base_name = os.path.splitext(os.path.basename(hst_file))[0]
        csv_file = os.path.join(output_folder, f"{base_name}.csv")
        if os.path.exists(csv_file):
            # Rename 'Time' to 'Timestamp'
            df = pd.read_csv(csv_file)
            df.rename(columns={'Time': 'Timestamp'}, inplace=True)
            df.to_csv(csv_file, index=False)
            print("  ✓ Renamed 'Time' to 'Timestamp' in CSV")
            
            size_mb = os.path.getsize(csv_file) / 1024 / 1024
            print(f"  → Created: {os.path.basename(csv_file)} ({size_mb:.1f} MB)")
            return csv_file
        return None
    except subprocess.CalledProcessError as e:
        print(f"✗ ERROR {os.path.basename(hst_file)}: {e}")
        return None

def create_bucket_if_not_exists(client, bucket_name):
    buckets_api = client.buckets_api()
    buckets = buckets_api.find_buckets(name=bucket_name)
    if len(buckets.buckets) == 0:
        buckets_api.create_bucket(bucket_name=bucket_name, org=INFLUX_ORG)
        print(f"  ✓ Created new bucket: {bucket_name}")

def insert_csv_to_influx(csv_file, hst_base_name):
    try:
        print(f"\n→ Inserting {os.path.basename(csv_file)} to InfluxDB...")
        df = pd.read_csv(csv_file, parse_dates=['Timestamp'])
        print(f"  Loaded {len(df):,} rows")
        
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        create_bucket_if_not_exists(client, INFLUX_BUCKET)
        write_api = client.write_api(write_options=SYNCHRONOUS)
        
        points = []
        batch_size = 5000
        total_written = 0
        
        for i, (_, row) in tqdm(enumerate(df.iterrows()), total=len(df), desc="Inserting data"):
            if pd.isna(row['Value']):
                continue  # Skip rows with NA/NaN in Value
            point = Point(hst_base_name).field("value", float(row['Value'])).time(row['Timestamp'], WritePrecision.S)
            points.append(point)
            if len(points) >= batch_size:
                write_api.write(bucket=INFLUX_BUCKET, record=points)
                total_written += len(points)
                points = []
        
        if points:
            write_api.write(bucket=INFLUX_BUCKET, record=points)
            total_written += len(points)
        
        client.close()
        print(f"  ✓ Inserted {total_written:,} points to InfluxDB (bucket: {INFLUX_BUCKET}, measurement: {hst_base_name})")
        
    except Exception as e:
        print(f"✗ Error inserting {csv_file}: {e}")

if __name__ == '__main__':
    freeze_support()
    
    print("🚀 Starting Citect HST to InfluxDB Pipeline")
    
    # User prompts
    input_folders = get_input_folders()
    output_mode, output_path = get_output_config(input_folders)
    
    csv_files = []
    for input_folder in input_folders:
        print(f"\nProcessing folder: {input_folder}")
        if output_mode == 'per_folder':
            current_output = os.path.join(input_folder, "output")
            os.makedirs(current_output, exist_ok=True)
        elif output_mode == 'single':
            current_output = output_path
        else:
            current_output = DEFAULT_OUTPUT_FOLDER
        
        hst_files = glob.glob(os.path.join(input_folder, "*.hst"))
        print(f"📋 Found {len(hst_files)} HST files in {input_folder}")
        
        for hst_file in hst_files:
            csv_file = process_hst_to_csv(hst_file, current_output)
            if csv_file:
                csv_files.append(csv_file)
    
    # Insert to InfluxDB
    print(f"\n📤 Inserting {len(csv_files)} CSVs to InfluxDB...")
    for csv_file in csv_files:
        hst_base = os.path.splitext(os.path.basename(csv_file))[0]
        insert_csv_to_influx(csv_file, hst_base)
    
    print("\n🎉 Pipeline COMPLETE! CSVs kept in output folders.")