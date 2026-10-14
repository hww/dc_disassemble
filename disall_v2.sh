#!/bin/bash

find . -name "*.bin" -type f | while read -r file; do
    echo "Processing: $file"
    python3 ./dc_disassemble_v2.py --dump-structs  "$file" "$@"
    echo "----------------------------------------"
done

find . -name "*/*.bin" -type f | while read -r file; do
    echo "Processing: $file"
    python3 ./dc_disassemble_v2.py --dump-structs  "$file" "$@"
    echo "----------------------------------------"
done

find . -name "*/*/*.bin" -type f | while read -r file; do
    echo "Processing: $file"
    python3 ./dc_disassemble_v2.py --dump-structs  "$file" "$@"
    echo "----------------------------------------"
done

find . -name "*/*/*/*.bin" -type f | while read -r file; do
    echo "Processing: $file"
    python3 ./dc_disassemble_v2.py --dump-structs  "$file" "$@"
    echo "----------------------------------------"
done