# HST to CSV Conversion Project - Technical Summary

## Project Overview
Converting 60,000 sensor data files from proprietary Citect HST format to CSV format for database insertion and analysis. The official Citect Trend app is too slow for this volume, so a custom parallel processing solution was developed.

## System Architecture

### Components
1. **trendconvert.py** - Core HST parser and CSV converter
2. **citect_wrapper.py** - Parallel processing orchestrator
3. **config.json** - Configuration file for paths and settings
4. **progress.json** - Tracks processed files for resume capability

### Environment
- **Language**: Python 3.12
- **OS**: Windows Server
- **Processing**: Multi-process parallel execution (configurable, default: CPU count - 2)

## HST File Format Specifications

### File Structure
- **Master Header (.HST file)**: Contains metadata and references to data files
- **Data Files (.000, .001, .002, etc.)**: Actual sensor readings

### Header Types
**Master Header (176 bytes)**:
- Title (128 bytes)
- ID (8 bytes)
- File Type (2 bytes)
- Version (2 bytes): `5` = 2-byte data, `6` = 8-byte data
- Max files, Files created, Next, Addon fields

**Data File Headers**:
- **Version 5 (Old Type)**: 144-byte filename + 128-byte header
- **Version 6 (New Type)**: 272-byte filename + 152-byte header

### Critical Header Fields
- **Version**: Determines data sample size (2-byte vs 8-byte)
- **SamplePeriod**: Time between samples in milliseconds
- **StartTime**: File start timestamp
- **EndTime**: File end timestamp
- **FilePointer**: **CRITICAL** - Number of valid samples (uninitialized data exists beyond this)
- **DataLength**: Total allocated space for samples
- **HistoryType**: 0 = Periodic Trend, 1 = Event Trend

### Data Sample Formats

**2-Byte Samples (Version 5)**:
- Raw integer values (0-32000 scale)
- Special values:
  - `-32001` = `<NA>` (invalid data)
  - `-32002` = `<GATED>` (gated data)
- Requires scaling: `EngValue = EngZero + ((RawValue - 0) / 32000) * (EngFull - EngZero)`

**8-Byte Samples (Version 6)**:
- IEEE 754 double-precision floating point
- Already in engineering units (no scaling needed)
- Special values:
  - `NaN` (Not a Number) = invalid data
  - Specific currency values for `<NA>` and `<GATED>`

### Timestamps
- **Version 5**: Unix timestamp (seconds since 1970-01-01)
- **Version 6**: Windows FILETIME (100-nanosecond intervals since 1601-01-01)
- **Sample timestamps**: `StartTime + (SamplePeriod * SampleIndex)`

## Key Technical Issues & Solutions

### Issue 1: Extra Rows in Output
**Problem**: Custom script produced 15,627,235 rows vs official app's 15,507,520 rows (~120k extra)

**Root Cause**: 
- Data files allocate space based on `DataLength` (total capacity)
- Only samples up to `FilePointer` index are valid
- Data beyond `FilePointer` is uninitialized memory

**Solution**:
```python
max_valid_samples = h.FilePointer

while True:
    bytes_read = f.read(sample_size)
    if not bytes_read:
        break
    
    # Skip uninitialized data
    if x >= max_valid_samples:
        x += 1
        continue
    
    # Process valid sample...
```

### Issue 2: File I/O Error (Closed File)
**Problem**: `ValueError: I/O operation on closed file` when processing multiple data files

**Root Cause**:
- Nested `with open()` contexts with similar variable names
- CSV file closed prematurely when processing subsequent data files

**Solution**:
- Use distinct variable names for nested file operations (`csv_file` vs `data_f`)
- Keep CSV file open for entire processing loop
- Only close after all data files are written

### Issue 3: Corrupted Progress File
**Problem**: `JSONDecodeError: Expecting value: line 1 column 1`

**Root Cause**: Empty or malformed `progress.json`

**Solution**:
```python
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    return set()
                return set(json.loads(content))
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning(f"Progress file corrupted: {e}. Starting fresh.")
            return set()
    return set()
```

## Data Filtering Rules

### Invalid Data Detection & Filtering
The official Citect app filters out:
1. **`<NA>`** - Invalid/missing data
   - 2-byte: value == -32001
   - 8-byte: isNaN(value)
2. **`<GATED>`** - Gated data (not collected during period)
   - 2-byte: value == -32002
   - 8-byte: specific currency value
3. **`<Uninitialized data>`** - Beyond FilePointer
   - Sample index >= FilePointer

### Implementation
```python
# 2-byte filtering
if value == -32001 or value == -32002:
    continue  # Skip NA and GATED

# 8-byte filtering
if math.isnan(value):
    continue  # Skip NA

# Both versions
if x >= max_valid_samples:
    continue  # Skip uninitialized
```

## Processing Workflow

### Single File Processing (trendconvert.py)
1. Parse master header from .HST file
2. Read all data file headers (sorted by StartTime)
3. Open single output CSV file
4. For each data file in chronological order:
   - Read engineering scales (RawZero, RawFull, EngZero, EngFull)
   - Read data header
   - For each sample up to FilePointer:
     - Skip invalid values (NA, GATED)
     - Calculate timestamp: `StartTime + (SamplePeriod * index)`
     - Scale value (2-byte only) or use directly (8-byte)
     - Write to CSV: `Timestamp,Value`
5. Close CSV file

### Parallel Processing (citect_wrapper.py)
1. Load configuration and progress tracking
2. Get input folder(s) from user
3. Scan for .HST files, skip if already processed or .csv.gz exists
4. Calculate total data size and estimate processing time
5. Process in batches (configurable size, default 200):
   - Spawn worker processes (configurable, default CPU-2)
   - Each worker:
     - Runs trendconvert.py on assigned .HST file
     - Renames "Time" column to "Timestamp"
     - Compresses CSV to .gz (configurable compression level)
     - Transfers .gz to shared output folder (VM #2)
     - Cleans up local temp files
   - Update progress.json after each batch
6. Log all operations with timestamps and file sizes

### Multi-Machine Architecture
- **VM #1**: HST parsing and CSV generation (this codebase)
- **VM #2**: Database insertion (separate process, reads from shared folder)
- **Shared Folder**: Network location for compressed CSV transfer

## File Naming Convention

### Input Files
- Master header: `SensorName.HST`
- Data files: `SensorName.000`, `SensorName.001`, etc.

### Output Files
- CSV: `SensorName.csv`
- Compressed: `SensorName.csv.gz`
- Logs: `wrapper_FolderName_YYYY-MM-DD_HH-MM-SS.log`

## Configuration (config.json)

```json
{
  "default_input_folder": "path/to/hst/files",
  "trendconvert_path": "path/to/trendconvert.py",
  "shared_output": "path/to/shared/folder",
  "progress_file": "progress.json",
  "temp_dir": "temp",
  "log_dir": "logs",
  "max_retries": 3,
  "gzip_level": 6
}
```

## Performance Metrics

### Baseline
- Official Citect app: Very slow for 60,000 files (days/weeks)
- Custom parallel solution: ~18.5 GB in 80 minutes

### Optimization Strategies
1. **Parallel Processing**: 10-20 concurrent processes
2. **Batch Processing**: Process 200 files per batch to manage memory
3. **Compression**: gzip level 6 for balance of speed/size
4. **Progress Tracking**: Resume capability after interruption
5. **Skip Already Processed**: Check progress.json and shared folder

## Data Validation

### Output Format
```csv
Timestamp,Value
2025-03-04 00:00:00,7.0
2025-03-04 00:00:01,7.0
```

### Verification
- Row count should match official Citect app output
- Timestamps should be continuous (based on SamplePeriod)
- Values should be in engineering units
- No `<NA>`, `<GATED>`, or `<Uninitialized>` data

## Error Handling

### Retry Logic
- Max retries: 3 (configurable)
- Logs all failures with full exception trace

### Common Errors
1. **File not found**: Skip and log
2. **Corrupted HST file**: Retry, then skip
3. **I/O errors**: Retry with exponential backoff
4. **Progress file corruption**: Reset and continue

## Command-Line Usage

### trendconvert.py
```bash
python trendconvert.py <file.HST> [options]

Options:
  -s                Strip directories from data filenames
  -o TYPE           Output type: csv (default) or xls
  -e                Examine master header (shows file dates)
  -start DATE       Start date filter (YYYY-MM-DD)
  -stop DATE        End date filter (YYYY-MM-DD)
  -f NUM            Select specific file index to export
  -p NUM            Decimal precision (default: 1)
  -outdir PATH      Output directory (default: current)
```

### citect_wrapper.py
```bash
python citect_wrapper.py

Interactive prompts:
- Use default input folder? (y/n)
- Single folder or text file with multiple? (s/t)
- Max processes? (default: CPU count - 2)
- Max HSTs per batch? (suggest: 200)
```

## Dependencies

```
pandas
logging
json
gzip
subprocess
multiprocessing
tqdm
influxdb_client (for future database insertion)
```

## Future Enhancements
1. Database insertion directly from VM #1 (currently done on VM #2)
2. Real-time monitoring dashboard
3. Automatic validation against original Citect app output
4. Cloud storage integration
5. Incremental updates for new sensor data

## Important Notes for AI Context

1. **FilePointer is critical** - Always filter samples beyond this index
2. **Version determines sample size** - Version 5 = 2 bytes, Version 6 = 8 bytes
3. **Timestamps use different epochs** - Version 5 = Unix, Version 6 = Windows FILETIME
4. **Data files must be sorted chronologically** - Sort by StartTime before processing
5. **Progress tracking is essential** - 60,000 files takes hours, need resume capability
6. **File variable naming matters** - Avoid shadowing in nested contexts
7. **Compression before transfer** - Reduces network overhead for VM-to-VM transfer

## Code Snippets Reference

### Critical Fix 1: FilePointer Check
```python
# In trendconvert.py main() function
max_valid_samples = h.FilePointer

while True:
    bytes_read = data_f.read(sample_size)
    if not bytes_read:
        break
    
    if x >= max_valid_samples:
        x += 1
        continue  # Skip uninitialized data
    
    # Process valid sample...
```

### Critical Fix 2: Nested File Handling
```python
# Open CSV once, keep open for all data files
with open(output_file, "w", newline="") as csv_file:
    writer = csv.writer(csv_file)
    writer.writerow(["Time", "Value"])
    
    for data_idx in datalist:
        # Use different variable name
        with open(data_file, "rb") as data_f:
            # Process data...
            writer.writerow([timestamp, value])
```

### Critical Fix 3: Progress File Recovery
```python
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    return set()
                return set(json.loads(content))
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning(f"Progress file corrupted: {e}. Starting fresh.")
            return set()
    return set()
```

## Troubleshooting Guide

### Problem: Too many rows in output
**Check**: Verify FilePointer filtering is implemented
**Solution**: Add `if x >= max_valid_samples: continue` before processing samples

### Problem: "I/O operation on closed file"
**Check**: Variable naming in nested file contexts
**Solution**: Use distinct names (`csv_file` vs `data_f`)

### Problem: Progress file corruption
**Check**: File exists but is empty or has invalid JSON
**Solution**: Delete file or initialize with `[]`

### Problem: Missing timestamps
**Check**: Data files not sorted by StartTime
**Solution**: Sort datalist by header.StartTime before processing

### Problem: Wrong values in 2-byte data
**Check**: Engineering scale factors applied correctly
**Solution**: Verify EngZero, EngFull, RawZero, RawFull from file header