# HST to CSV Conversion Project --- Technical Summary (Updated 2025 Edition)

## Project Overview

This system converts large volumes of Citect HST historical trend files
into CSV format for insertion into an analytical database. The Citect
Trend Viewer is too slow for this scale (\>60,000 HST files), so a
high-throughput, parallelized, fault-tolerant processing pipeline was
built.

This document includes **major upgrades introduced in Dec 2025**,
including:

-   Adaptive RAM control\
-   Robust multiprocessing logging system\
-   Python 3.12-compatible architecture\
-   Worker-level isolation\
-   Multi-file success/failure tracking\
-   Folder-signature-based unique naming\
-   Rich summary output and audit tools

## System Architecture

### Core Components

1.  **trendconvert.py**\
    Parses HST + .00X data segments and outputs CSV.\
2.  **citect_wrapper.py**\
    High-level Orchestrator:
    -   parallel processing\
    -   logging\
    -   compression\
    -   renaming\
    -   safe transfer\
3.  **config.json**\
    Defines paths, retries, and compression level.\
4.  **progress.json**\
    Tracks previously processed files for resume capability.\
5.  **run folder output**\
    Each run creates:
    -   `wrapper.log`\
    -   `successes.log`, `failures.log`, `skipped.log`\
    -   `summary.json`

### New Architecture Improvements (Dec 2025)

  Component         Upgrade
  ----------------- --------------------------------------------------
  Multiprocessing   Fully Python 3.12 compatible (no pickled queues)
  Logging           Dedicated listener process + worker queues
  Memory            psutil-based RAM throttling (75% cap)
  CSV Renaming      Streaming line-edit system---no full CSV loaded
  Temp Handling     Per-worker isolated temp dirs
  File Naming       Duplicate-safe folder signature hashing
  Summary           JSON stats + success/failure/skip logs
  Input Modes       Folder scan OR text list (for duplicate groups)

## New: Worker-Safe Logging System

Windows + Python 3.12 uses the `spawn` method. Passing a Queue to
workers raises runtime errors.\
Solution: workers inherit a queue through `initializer`.

## New: RAM Limiter (psutil)

Workers pause when RAM exceeds 75%.

## New: Streaming CSV Column Rename

Zero-memory rename of `Time` → `Timestamp`.

## New: Per-Worker Temp Directories

Each worker gets its own safe isolated temp folder.

## New: Duplicate-Safe File Naming

Normalized folder signatures ensure unique output filenames.

## New: Batch Architecture With Progress Tracking

-   Batching (default 200)
-   Resumable via `progress.json`

## Summary.json Structure

Includes counts, timing, success/failure metrics.

## Processing Workflow (Updated)

1.  Load config\
2.  Start logging listener\
3.  Acquire input paths\
4.  Batch processing\
5.  For each file: convert, rename, compress, transfer, log\
6.  Write summary\
7.  Shutdown listener

## Future Enhancements

-   Full HST audit tool (TrendScan)
-   Duplicate detection reports
-   Remote monitoring
-   Scheduled incremental runs
