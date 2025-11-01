import os
import glob
import pandas as pd
import logging
import json
import gzip
import shutil
import time
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketsApi
from influxdb_client.client.write_api import SYNCHRONOUS
import subprocess
from datetime import datetime
from multiprocessing import Pool, cpu_count, freeze_support
from tqdm import tqdm

# Load config from JSON
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if not os.path.exists(config_path):
        logging.error(f"Config file not found: {config_path}")
        exit(1)
    with open(config_path, 'r') as f:
        return json.load(f)

CONFIG = load_config()

DEFAULT_INPUT_FOLDER = CONFIG['default_input_folder']
TRENDCONVERT_PATH = CONFIG['trendconvert_path']
SHARED_OUTPUT = CONFIG['shared_output']
PROGRESS_FILE = CONFIG['progress_file']
LOG_FILE = CONFIG['log_file']
TEMP_DIR = CONFIG['temp_dir']
MAX_TEMP_SIZE_GB = CONFIG['max_temp_size_gb']  # e.g., 3

os.makedirs(TEMP_DIR, exist_ok=True)

# Logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_progress(processed):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(list(processed), f)

def get_temp_size():
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(TEMP_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return total_size / (1024 * 1024 * 1024)  # GB

def clean_temp_if_needed():
    while get_temp_size() > MAX_TEMP_SIZE_GB * 0.8:  # Clean at 80% threshold
        files = glob.glob(os.path.join(TEMP_DIR, '*'))
        if not files:
            break
        oldest_file = min(files, key=os.path.getctime)
        os.remove(oldest_file)
        logging.info(f"Cleaned temp file: {oldest_file}")

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

def process_hst_to_csv(hst_file):
    start_time = time.perf_counter()
    cmd = ["python", TRENDCONVERT_PATH, hst_file, "-o", "csv", "-s", "-outdir", TEMP_DIR]
    for attempt in range(3):
        try:
            result = subprocess.run(cmd, capture_output=False, text=True, check=True)
            logging.info(f"✓ Processed {os.path.basename(hst_file)}")
            
            base_name = os.path.splitext(os.path.basename(hst_file))[0]
            csv_temp = os.path.join(TEMP_DIR, f"{base_name}.csv")
            if os.path.exists(csv_temp):
                # Rename 'Time' to 'Timestamp'
                df = pd.read_csv(csv_temp)
                df.rename(columns={'Time': 'Timestamp'}, inplace=True)
                df.to_csv(csv_temp, index=False)
                logging.info("  ✓ Renamed 'Time' to 'Timestamp' in CSV")
                
                # Compress (level=6 for speed)
                gz_temp = csv_temp + '.gz'
                with open(csv_temp, 'rb') as f_in, gzip.open(gz_temp, 'wb', compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
                logging.info(f"  ✓ Compressed {base_name}.csv.gz")
                
                # Copy to shared
                gz_shared = os.path.join(SHARED_OUTPUT, os.path.basename(gz_temp))
                shutil.copy(gz_temp, gz_shared)
                logging.info(f"  ✓ Transferred {base_name}.csv.gz to shared")
                
                # Clean temp immediately
                os.remove(csv_temp)
                os.remove(gz_temp)
                
                clean_temp_if_needed()  # Extra clean if near limit
                
                elapsed = time.perf_counter() - start_time
                logging.info(f"  Time: {elapsed:.2f}s")
                return gz_shared
            return None
        except Exception as e:
            logging.warning(f"Attempt {attempt+1} failed for {hst_file}: {e}")
    logging.error(f"✗ Failed {os.path.basename(hst_file)} after 3 attempts")
    return None

if __name__ == '__main__':
    freeze_support()
    
    logging.info("🚀 Starting HST to CSV on VM #1 (saves compressed to VM #2 shared)")
    
    # User prompts
    input_folders = get_input_folders()
    max_processes = int(get_user_input(f"Max processes (default {cpu_count() - 2}): ", cpu_count() - 2))
    batch_size = int(get_user_input("Max HSTs per batch (for large data, suggest 200): ", 200))
    
    processed = load_progress()
    
    # Collect tasks, skip processed
    tasks = []
    for input_folder in input_folders:
        logging.info(f"\nProcessing folder: {input_folder}")
        hst_files = glob.glob(os.path.join(input_folder, "*.hst"))
        logging.info(f"📋 Found {len(hst_files)} HST files")
        for hst in hst_files:
            if hst not in processed:
                tasks.append(hst)
    
    # Process in batches
    csv_files = []
    total_start = time.perf_counter()
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        logging.info(f"\nParallel processing batch {i//batch_size + 1} ({len(batch)} files)...")
        with Pool(processes=max_processes) as pool:
            batch_csvs = list(tqdm(pool.imap(process_hst_to_csv, batch), total=len(batch), desc="Converting HSTs"))
        csv_files.extend([c for c in batch_csvs if c])
        # Update progress
        processed.update([t for t in batch if process_hst_to_csv(t)])  # Only add successful
        save_progress(processed)
    
    total_elapsed = time.perf_counter() - total_start
    logging.info(f"\nTotal time: {total_elapsed / 3600:.2f} hours")
    logging.info("\n🎉 CSVs (compressed) saved to VM #2 shared folder. Run inserter on VM #2.")