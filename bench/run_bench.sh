#!/usr/bin/env bash
# I/O benchmark: NVMe (local) vs external USB3 SSD (exFAT). Sequential + 4K random.
set -u
run_target () {
  local name="$1" dir="$2" direct="$3"
  mkdir -p "$dir"
  echo "############################################################"
  echo "# TARGET: $name  ($dir)  direct=$direct"
  echo "############################################################"
  fio --name=seqwrite --directory="$dir" --rw=write --bs=1M --size=2G \
      --direct="$direct" --numjobs=1 --iodepth=1 --end_fsync=1 --group_reporting 2>&1 | grep -E "WRITE:"
  fio --name=seqread --directory="$dir" --rw=read --bs=1M --size=2G \
      --direct="$direct" --numjobs=1 --iodepth=1 --group_reporting 2>&1 | grep -E "READ:"
  fio --name=randread --directory="$dir" --rw=randread --bs=4k --size=1G \
      --direct="$direct" --ioengine=libaio --iodepth=32 --runtime=12 --time_based --group_reporting 2>&1 | grep -E "read: IOPS|READ:"
  fio --name=randwrite --directory="$dir" --rw=randwrite --bs=4k --size=1G \
      --direct="$direct" --ioengine=libaio --iodepth=32 --runtime=12 --time_based --group_reporting 2>&1 | grep -E "write: IOPS|WRITE:"
  rm -f "$dir"/seqwrite.* "$dir"/seqread.* "$dir"/randread.* "$dir"/randwrite.*
}

# NVMe supports O_DIRECT. exFAT often does not -> preflight and fall back to buffered.
EXT_DIRECT=1
if ! fio --name=t --directory=/mnt/ext/bench --rw=write --bs=4k --size=4k --direct=1 --numjobs=1 >/dev/null 2>&1; then
  EXT_DIRECT=0
fi
rm -f /mnt/ext/bench/t.* 2>/dev/null

run_target "NVMe (local ext4)" "/home/arian/Programming/DenmarkAPI/bench/io" 1
run_target "External USB3 SSD (exFAT)" "/mnt/ext/bench" "$EXT_DIRECT"
echo "DONE"
