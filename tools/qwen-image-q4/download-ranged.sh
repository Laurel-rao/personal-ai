#!/bin/sh
set -eu

if [ "$#" -lt 4 ]; then
  echo "用法: $0 URL 输出文件 总字节数 并发数" >&2
  exit 2
fi

URL=$1
OUTPUT=$2
TOTAL=$3
PARTS=$4
WORK="${OUTPUT}.ranges"
mkdir -p "$WORK"

index=0
while [ "$index" -lt "$PARTS" ]; do
  start=$((TOTAL * index / PARTS))
  end=$((TOTAL * (index + 1) / PARTS - 1))
  part="$WORK/$(printf '%03d' "$index").part"
  if [ -f "$part" ] && [ "$(stat -f '%z' "$part")" -eq $((end - start + 1)) ]; then
    index=$((index + 1))
    continue
  fi
  rm -f "$part"
  curl -L --fail --retry 20 --retry-all-errors --connect-timeout 20 \
    -H "Range: bytes=$start-$end" "$URL" -o "$part" \
    >"$WORK/$(printf '%03d' "$index").log" 2>&1 &
  index=$((index + 1))
done

status=0
index=0
while [ "$index" -lt "$PARTS" ]; do
  wait || status=1
  index=$((index + 1))
done
if [ "$status" -ne 0 ]; then
  echo "分片下载失败，日志位于 $WORK" >&2
  exit 1
fi

temporary="$OUTPUT.combine"
rm -f "$temporary"
index=0
while [ "$index" -lt "$PARTS" ]; do
  part="$WORK/$(printf '%03d' "$index").part"
  expected_start=$((TOTAL * index / PARTS))
  expected_end=$((TOTAL * (index + 1) / PARTS - 1))
  expected_size=$((expected_end - expected_start + 1))
  actual_size=$(stat -f '%z' "$part")
  if [ "$actual_size" -ne "$expected_size" ]; then
    echo "分片大小错误: $part ($actual_size != $expected_size)" >&2
    exit 1
  fi
  cat "$part" >> "$temporary"
  index=$((index + 1))
done
mv "$temporary" "$OUTPUT"
echo "完成: $OUTPUT ($(stat -f '%z' "$OUTPUT") bytes)"
