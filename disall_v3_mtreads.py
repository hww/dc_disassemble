#!/bin/bash
#
# disasm_all_parallel.sh — параллельная версия
#

set -euo pipefail

INPUT_DIR="${1:-.}"
OUTPUT_DIR="${2:-asm}"
PARALLEL="${3:-4}"     # число параллельных процессов
shift 3 2>/dev/null || true
EXTRA_ARGS=("$@")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISASM_SCRIPT="${SCRIPT_DIR}/dc_disassemble_v3.py"

if [[ ! -f "$DISASM_SCRIPT" ]]; then
    echo "ERROR: не найден $DISASM_SCRIPT" >&2
    exit 1
fi

if [[ ! -d "$INPUT_DIR" ]]; then
    echo "ERROR: не найдена папка $INPUT_DIR" >&2
    exit 1
fi

echo "========================================"
echo "  Вход:      $INPUT_DIR"
echo "  Выход:     $OUTPUT_DIR"
echo "  Параллель: $PARALLEL"
echo "========================================"
echo

# Функция для одного файла
process_one() {
    local file="$1"
    local rel="${file#$INPUT_DIR/}"
    local rel_asm="${rel%.bin}.asm"
    local out_file="${OUTPUT_DIR}/${rel_asm}"

    mkdir -p "$(dirname "$out_file")"

    if python3 "$DISASM_SCRIPT" --dump-structs "${EXTRA_ARGS[@]}" "$file" \
            > "$out_file" 2>"${out_file}.err"; then
        if [[ -s "$out_file" ]]; then
            rm -f "${out_file}.err"
            echo "OK   $rel"
        else
            mv "${out_file}.err" "${out_file}"
            echo "FAIL $rel (empty)"
        fi
    else
        echo "FAIL $rel (crash)"
    fi
}

export -f process_one
export INPUT_DIR OUTPUT_DIR DISASM_SCRIPT
# EXTRA_ARGS нельзя экспортировать как массив — используем строку
EXTRA_ARGS_STR="${EXTRA_ARGS[*]:-}"
export EXTRA_ARGS_STR

# Переписываем process_one с использованием строки
process_one_export() {
    local file="$1"
    local rel="${file#$INPUT_DIR/}"
    local rel_asm="${rel%.bin}.asm"
    local out_file="${OUTPUT_DIR}/${rel_asm}"

    mkdir -p "$(dirname "$out_file")"

    local args=()
    if [[ -n "$EXTRA_ARGS_STR" ]]; then
        read -ra args <<< "$EXTRA_ARGS_STR"
    fi

    if python3 "$DISASM_SCRIPT" --dump-structs "${args[@]}" "$file" \
            > "$out_file" 2>"${out_file}.err"; then
        if [[ -s "$out_file" ]]; then
            rm -f "${out_file}.err"
            echo "OK   $rel"
        else
            mv "${out_file}.err" "${out_file}"
            echo "FAIL $rel (empty)"
        fi
    else
        echo "FAIL $rel (crash)"
    fi
}
export -f process_one_export

# Находим файлы
mapfile -d '' FILES < <(find "$INPUT_DIR" -type f -name "*.bin" -print0 | sort -z)
TOTAL=${#FILES[@]}

if [[ $TOTAL -eq 0 ]]; then
    echo "Не найдено .bin в $INPUT_DIR"
    exit 0
fi

echo "Найдено $TOTAL файлов"
echo

# Параллельный запуск
printf '%s\0' "${FILES[@]}" | \
    xargs -0 -n 1 -P "$PARALLEL" -I {} bash -c 'process_one_export "$@"' _ {}

echo
echo "========================================"
echo "  Готово!"
echo "========================================"