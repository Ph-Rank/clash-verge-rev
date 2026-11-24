"""Compare stock and single-worker Mihomo configuration checks on Windows.

Example from the folder containing this file:
    python reproduce-validation.py --attempts 40

Each check uses -t, a temporary data directory, bundled geo assets and a
synthetic ruleset. The script launches and stops only its own test processes.
"""

import argparse
from collections import Counter
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_core = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Clash Verge/verge-mihomo.exe"
    parser.add_argument("--core", type=Path, default=default_core)
    parser.add_argument("--resources", type=Path, help="directory containing the bundled geo files")
    parser.add_argument("--work-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--attempts", type=int, default=40, help="checks per mode")
    parser.add_argument("--timeout", type=float, default=5.0, help="observation window in seconds")
    args = parser.parse_args()
    if args.attempts < 1 or args.timeout <= 0:
        parser.error("attempts and timeout must be positive")
    core = args.core.resolve(strict=True)
    resources = args.resources or core.parent / "resources"
    counts = Counter()
    timings = {"stock": [], "single-worker": []}
    rng = random.Random(19033)

    with tempfile.TemporaryDirectory(dir=args.work_dir.resolve(strict=True)) as temp:
        root = Path(temp)
        copy = root / ("fixture-mihomo" + core.suffix)
        shutil.copy2(core, copy)
        for name in ("geosite.dat", "geoip.dat", "Country.mmdb", "ASN.mmdb"):
            shutil.copy2(resources / name, root / name)
        config = root / "fixture.yaml"
        config.write_text(
            "mixed-port: 0\nallow-lan: false\ntun: {enable: false}\ndns: {enable: false}\n"
            "geo-auto-update: false\n"
            "geox-url: {geosite: 'http://127.0.0.1:1/unused', geoip: 'http://127.0.0.1:1/unused', "
            "mmdb: 'http://127.0.0.1:1/unused', asn: 'http://127.0.0.1:1/unused'}\n"
            "rules:\n  - GEOSITE,cn,DIRECT\n"
            + "".join(f"  - DOMAIN-SUFFIX,host{i}.example.test,DIRECT\n" for i in range(2900))
            + "  - GEOIP,CN,DIRECT,no-resolve\n  - MATCH,DIRECT\n",
            encoding="utf-8",
        )
        for index in range(1, args.attempts + 1):
            modes = list(timings)
            rng.shuffle(modes)
            for mode in modes:
                env = os.environ.copy()
                env.pop("GOMAXPROCS", None)
                if mode == "single-worker":
                    env["GOMAXPROCS"] = "1"
                start = time.monotonic()
                with subprocess.Popen(
                    [copy, "-t", "-d", root, "-f", config], cwd=root, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ) as child:
                    try:
                        output, _ = child.communicate(timeout=args.timeout)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        output, _ = child.communicate()
                        counts[mode, "pending"] += 1
                        lines = output.splitlines()
                        geo = bool(lines and b"Load GeoSite rule: cn" in lines[-1])
                        print(f"{mode}, run {index}: pending at {args.timeout:g}s, last line GeoSite cn={geo}", flush=True)
                        continue
                    if child.returncode:
                        raise SystemExit(output.decode(errors="replace"))
                    timings[mode].append(time.monotonic() - start)
        for mode, times in timings.items():
            median = f"{statistics.median(times):.3f}s" if times else "n/a"
            print(f"{mode}: {len(times)} completed, {counts[mode, 'pending']} pending, median completed {median}")


if __name__ == "__main__":
    main()
