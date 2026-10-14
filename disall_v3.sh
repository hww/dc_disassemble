#!/bin/bash
#
# disasm_all.sh — дизассемблирует все .bin файлы в отдельные .asm
#
# Использование:
#   ./disasm_all.sh [input_dir] [output_dir] [доп. флаги dc_disassemble_v3.py]
#
# Примеры:
#   ./disasm_all.sh                                    # ./dc1 → ./asm
#   ./disasm_all.sh dc1                                # dc1 → ./asm
#   ./disasm_all.sh dc1 out_asm --max-structs 0        # dc1 → out_asm, без лимита
#   ./disasm_all.sh dc1 out_asm --verbose              # с отладкой
#

set -euo pipefail

# ---------- Аргументы ----------
INPUT_DIR="${1:-.}"
OUTPUT_DIR="${2:-asm}"
shift 2 2>/dev/null || true
EXTRA_ARGS=("$@")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISASM_SCRIPT="${SCRIPT_DIR}/dc_disassemble_v3.py"

# ---------- Проверки ----------
if [[ ! -f "$DISASM_SCRIPT" ]]; then
    echo "ERROR: не найден $DISASM_SCRIPT" >&2
    exit 1
fi

if [[ ! -d "$INPUT_DIR" ]]; then
    echo "ERROR: не найдена папка $INPUT_DIR" >&2
    exit 1
fi

# ---------- Подсчёт файлов ----------
mapfile -d '' FILES < <(find "$INPUT_DIR" -type f -name "*.bin" -print0 | sort -z)
TOTAL=${#FILES[@]}

if [[ $TOTAL -eq 0 ]]; then
    echo "Не найдено ни одного .bin в $INPUT_DIR" >&2
    exit 0
fi

echo "========================================"
echo "  Найдено файлов: $TOTAL"
echo "  Входная папка:  $INPUT_DIR"
echo "  Выходная папка: $OUTPUT_DIR"
echo "  Скрипт:         $DISASM_SCRIPT"
echo "  Доп. флаги:     ${EXTRA_ARGS[*]:-<нет>}"
echo "========================================"
echo

# ---------- Счётчики ----------
OK=0
FAIL=0
SKIP=0
FAILED_FILES=()

# ---------- Основной цикл ----------
i=0
for file in "${FILES[@]}"; do
    i=$((i + 1))

    # Относительный путь от INPUT_DIR
    rel="${file#$INPUT_DIR/}"

    # Заменяем .bin на .asm
    rel_asm="${rel%.bin}.asm"

    # Полный путь к выходному файлу
    out_file="${OUTPUT_DIR}/${rel_asm}"

    # Создаём папку, если её нет
    out_dir="$(dirname "$out_file")"
    mkdir -p "$out_dir"

    printf '[%d/%d] %s\n' "$i" "$TOTAL" "$rel"

    # Запускаем дизассемблер, перенаправляя stdout в файл
    if python3 "$DISASM_SCRIPT" --dump-structs "${EXTRA_ARGS[@]}" "$file" > "$out_file" 2>"${out_file}.err"; then
        # Проверяем, что файл не пустой
        if [[ -s "$out_file" ]]; then
            rm -f "${out_file}.err"
            OK=$((OK + 1))
        else
            echo "  WARNING: пустой выход — сохраняю stderr"
            mv "${out_file}.err" "${out_file}"
            FAIL=$((FAIL + 1))
            FAILED_FILES+=("$rel")
        fi
    else
        echo "  ERROR: дизассемблер упал (см. ${out_file}.err)"
        FAIL=$((FAIL + 1))
        FAILED_FILES+=("$rel")
    fi
done

# ---------- Итог ----------
echo
echo "========================================"
echo "  Готово!"
echo "  OK:    $OK"
echo "  FAIL:  $FAIL"
echo "========================================"

if [[ $FAIL -gt 0 ]]; then
    echo
    echo "Провалившиеся файлы:"
    for f in "${FAILED_FILES[@]}"; do
        echo "  - $f"
    done
    exit 1
fi

exit 0