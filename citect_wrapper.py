import os
import glob
import pandas as pd
import logging
import json
import gzip
import shutil
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketsApi
from influxdb_client.client.write_api import SYNCHRONOUS
import subprocess
from datetime import datetime
from multiprocessing import Pool, cpu_count, freeze_support
from tqdm import tqdm

# Config
DEFAULT_INPUT_FOLDER = r"D:\khayyamian\Hamid\data"
TRENDCONVERT_PATH = r"D:\khayyamian\Hamid\trendconvert\trendconvert.py"
SHARED_OUTPUT = r'\\WIN-QK1JS7CVQ3C\Users\Administrator\Desktop\Elahi Test'  # VM #2 shared
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), 'processed_hsts.json')  # Resume tracking
LOG_FILE = os.path.join(os.path.dirname(__file__), 'wrapper.log')

# Setup logging
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
    cmd = ["python", TRENDCONVERT_PATH, hst_file, "-o", "csv", "-s", "-outdir", os.path.dirname(SHARED_OUTPUT)]
    for attempt in range(3):
        try:
            result = subprocess.run(cmd, capture_output=False, text=True, check=True)
            logging.info(f"✓ Processed {os.path.basename(hst_file)}")
            
            base_name = os.path.splitext(os.path.basename(hst_file))[0]
            csv_file = os.path.join(os.path.dirname(SHARED_OUTPUT), f"{base_name}.csv")
            if os.path.exists(csv_file):
                # Rename 'Time' to 'Timestamp'
                df = pd.read_csv(csv_file)
                df.rename(columns={'Time': 'Timestamp'}, inplace=True)
                df.to_csv(csv_file, index=False)
                logging.info("  ✓ Renamed 'Time' to 'Timestamp' in CSV")
                
                # Compress and copy to shared
                gz_file = csv_file + '.gz'
                with open(csv_file, 'rb') as f_in, gzip.open(gz_file, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                shutil.copy(gz_file, SHARED_OUTPUT)
                os.remove(csv_file)  # Clean temp
                os.remove(gz_file)
                logging.info(f"  ✓ Compressed and transferred {base_name}.csv.gz to shared")
                return os.path.join(SHARED_OUTPUT, f"{base_name}.csv.gz")
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
    batch_size = int(get_user_input("Max HSTs per batch (for 6TB, suggest 100): ", 100))
    
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
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        logging.info(f"\nParallel processing batch {i//batch_size + 1} ({len(batch)} files)...")
        with Pool(processes=max_processes) as pool:
            batch_csvs = list(tqdm(pool.imap(process_hst_to_csv, batch), total=len(batch), desc="Converting HSTs"))
        csv_files.extend([c for c in batch_csvs if c])
        # Update progress
        processed.update(batch)
        save_progress(processed)
    
    logging.info("\n🎉 CSVs (compressed) saved to VM #2 shared folder. Run inserter on VM #2.")